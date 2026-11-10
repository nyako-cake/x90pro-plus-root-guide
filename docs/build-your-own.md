# 自己构建适配包（Build Your Own）

> 为什么发脚本而不是发成品 APK：DirtyFrag 的临时 root 包和**具体内核**强绑定（符号 CRC、vermagic、exploit 偏移），
> 换一个固件就不能用。正确做法是用你自己的 OTA 镜像，在本地重新生成一份只属于你设备的包。

---

## 兼容性矩阵

| 机型 | 系统 | 内核 | 状态 |
|---|---|---|---|
| vivo X90 Pro+（PD2227 / V2227A） | `PD2227_A_14.1.15.11.W10.V000L1` | `5.15.137-ge30fcc60efc0-dirty` | ✅ 本仓库实测 |
| vivo X90 Pro+（PD2227 / V2227A） | `PD2227C_A_15.2.11.1.W10.V000L1` | `5.15.178-gf4fc3f9ca234-dirty` | ⚠️ 需按本文重做 CRC/vermagic，未验证 |
| 其他 vivo / iQOO | 任意 | 任意 | ❌ 不保证，需自行适配 exploit 链与分区布局 |
| 其他品牌 | 任意 | 任意 | ❌ 不适用 |

> 判断标准：`uname -r` 必须与你要适配的内核**完全一致**；CRC 表来自这台机器的内核，差一个构建都不行。

---

## 前置条件

- 你**自己的**完整 OTA 包（`payload.bin`，或已解出的 `boot.img`）
- Windows / Linux / macOS 任一，装好：
  - Python 3.9+，`pip install pyelftools`
  - [vmlinux-to-elf](https://github.com/marin-m/vmlinux-to-elf)
  - Android NDK **r27c**（`$env:NDK` 指向根目录）
  - Android build-tools（`zipalign`、`apksigner`）
  - JDK（`keytool`）
  - 一台能装 APK 的目标手机
- DirtyFrag-vr 源码（`app/src/main/jni`，含 8 个 `ko/dfroot-*.ko` 与 `splicehelper.c`、`exp.c`、`libcxx.S`、`elf_parser.c`）

---

## 构建流程（按顺序）

### 1. 从 OTA 提取 boot.img

```sh
python scripts/extract_payload.py payload.bin --list
python scripts/extract_payload.py payload.bin boot boot.img
```

### 2. 取出内核 Image

`boot.img` 的 kernel 从偏移 4096 开始：

```sh
dd if=boot.img of=Image bs=4096 skip=1
```

### 3. 恢复符号并导出 CRC

```sh
# 基址按你的内核实际值填；PD2227 是 0xffffffc080000000
vmlinux-to-elf --base-address 0xffffffc080000000 Image vmlinux.elf

python scripts/kernel_crcs.py vmlinux.elf --out crcs.json \
  --symbols module_layout,snprintf,register_kprobe,_printk,unregister_kprobe,strcmp,\
__ubsan_handle_cfi_check_fail_abort,arm64_const_caps_ready,cpu_hwcap_keys,cpu_hwcaps,memset,__stack_chk_fail \
  --symbol-shift 0x78000000
```

> `--symbol-shift` 用于修正 vmlinux-to-elf 的基址偏差；PD2227 的 5.15.137 需要 `0x78000000`。
> 换内核时如果 CRC 校验一直失败，先确认这个偏移。

### 4. 拆出 DirtyFrag 内嵌的 ko

```sh
python scripts/extract_kos.py path/to/libdfroot.so kos/
```

会得到 `dfroot-android13-5.15.ko` 等 8 个模块。

### 5. 给目标 ko 打补丁

```sh
python scripts/patch_ko.py kos/dfroot-android13-5.15.ko \
  --crcs crcs.json \
  --vermagic "$(uname -r) SMP preempt mod_unload modversions vivo aarch64" \
  --out kos/dfroot-patched.ko
```

vermagic 必须与目标内核 `/proc/version` 里的完整字符串一致（注意 `vivo` 段）。

### 6. 替换 ko 并重编 libdfroot.so

把 `kos/dfroot-patched.ko` 覆盖回 DirtyFrag 源码的 `ko/dfroot-android13-5.15.ko`，然后：

```powershell
$env:NDK = "C:\path\to\android-ndk-r27c"
.\scripts\build_dfroot.ps1 -Source C:\path\to\DirtyFrag\app\src\main\jni -OutDir .\build
```

### 7. 修改 bootstrap（可选但建议）

在 `bootstrap.c` 中：

- `main()` 开头 `dd` 出 `devinfo` 到 `/data/local/tmp/devinfo.img`；
- 若存在 `/data/local/tmp/devinfo_patched.img`，写回 `devinfo` 并 `touch("/dev/dfunlock")`；
- `ksud late-load` 加 `--kmi android13-5.15`（vivo 内核串没有 `androidNN`，自动识别会失败）。

改完重新执行第 6 步。

### 8. 替换 APK 内的 so 并重签

```sh
python scripts/repack_apk.py base.apk unsigned.apk \
  lib/arm64-v8a/libdfroot.so=build/libdfroot.so \
  lib/arm64-v8a/libbootstrap.so=build/libbootstrap.so

keytool -genkeypair -keystore my.jks -alias me -keyalg RSA -keysize 2048 -validity 10000
zipalign -f -p 4 unsigned.apk aligned.apk
apksigner sign --ks my.jks --ks-pass pass:<你的密码> --out signed.apk aligned.apk
```

### 9. 安装与验证

```sh
adb install -r signed.apk
# 打开 App，等待 hook 完成

adb shell "su -c id"
# uid=0(root) gid=0(root) ...
```

成功后即可进行下一步（devinfo 解锁 / 或临时使用 root）。

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `insmod: Exec format error` | ko 没有 `__versions`，或 `CONFIG_MODULE_FORCE_LOAD=n` | 确认第 5 步的 CRC 表来自本机内核 |
| `version magic ... should be ...` | vermagic 不匹配 | 用 `/proc/version` 的完整字符串重打 |
| CRC 全对但仍加载失败 | `--symbol-shift` 不对 | 调整偏移重新导出 CRC |
| 加载成功但拿不到 root | exploit 链偏移不匹配 / hook 未触发 | 确认内核版本完全一致；查看 `/data/local/tmp` 诊断日志 |
| App 装不上 | 签名冲突 | 先卸载旧版，或用 `adb install -r -d` |

---

## 风险与边界

- 这是**提权 exploit**，仅用于你自己的设备；请勿用于他人设备。
- 会修改系统内存/页缓存，可能导致崩溃、数据损坏或变砖。
- 仅对**完全一致的内核构建**有效；不同 OTA 请重做本文流程。
- 本仓库不附带厂商专有二进制；请从你自己的 OTA/设备中提取。
