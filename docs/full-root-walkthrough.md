# vivo X90 Pro+（PD2227）完整 root 过程：工具、方法、顺序

> 本文按时间顺序记录整条 root 链路：每个阶段做了什么、用了什么工具、为什么这样做、如何验证、踩了什么坑。
> 最终状态：**bootloader 已解锁 + Android 15 + SukiSU LKM 持久 root + vr.ko 已屏蔽**。

---

## 0. 总览时间线

| # | 阶段 | 目标 | 关键工具 | 产物 | 验证 |
|---|---|---|---|---|---|
| 1 | 侦察与可行性 | 判断 DirtyFrag 能否在本机跑通 | adb、Python、内核配置解析 | 可行性结论 + 内核参数表 | 模块加载失败原因定位 |
| 2 | 临时 root | 拿到 uid=0 以便写 devinfo | DirtyFrag-vr 源码、NDK r27c、pyelftools、vmlinux-to-elf、apksigner | `dfroot-signed.apk` | `su -c id` → uid=0 |
| 3 | 解锁 BL | 改写 devinfo 解锁 bootloader | adb、dd、fastboot | `devinfo_patched.img` | `fastboot oem device-info` 显示 unlocked |
| 4 | 持久 root | 重启不丢的 KernelSU | KernelSU 管理器、fastboot | `init_boot_patched.img` | `kernelsu ... Live` + `su` |
| 5 | 切换 SukiSU | 换用模块页更兼容的分支 | SukiSU-Ultra APK、ksud | `init_boot_sukisu.img` | 管理器「工作中 · LKM」 |
| 6 | OTA 到 Android 15 | 升级系统且保留 root | 系统 OTA、ksud `boot-patch`、fastboot | `init_boot_a_novr.img` | Android 15 + `su` |
| 7 | vr.ko 修复 | 解决模块页无限加载 | ksud `--block-module vr` | 同上（重打补丁） | 模块页正常、`/proc/modules` 无 vr |

---

## 1. 设备与环境

| 项 | 值 |
|---|---|
| 机型 | vivo X90 Pro+（V2227A / PD2227） |
| SoC | Snapdragon 8 Gen 2（SM8550 / kalama） |
| 初始系统 | `PD2227_A_14.1.15.11.W10.V000L1`（Android 14） |
| 初始内核 | `5.15.137-ge30fcc60efc0-dirty` |
| 升级后系统 | `PD2227C_A_15.2.11.1.W10.V000L1`（Android 15 / SDK 35） |
| 升级后内核 | `5.15.178-gf4fc3f9ca234-dirty` |
| 分区布局 | A/B（`boot_a/b`、`init_boot_a/b`、`vendor_boot` 等） |
| 安全状态 | 解锁后 `ro.boot.flash.locked=0`、`verifiedbootstate=orange` |

---

## 2. 工具清单：用了什么、实现了什么

| 工具 | 版本/来源 | 用来做什么 | 产出 |
|---|---|---|---|
| **adb / fastboot** | Android platform-tools | 设备调试、进 bootloader、刷分区 | 全流程 |
| **Python 3** | 本机 | 解析 payload、ELF/ko、镜像头、生成补丁 | `scripts/*.py` |
| **pyelftools** | pip | 解析 `libdfroot.so` 里的 8 个 ko、注入 `__versions` | 重打包后的 ko |
| **vmlinux-to-elf** | GitHub | 从 `Image` 恢复 kallsyms/符号 | `vmlinux.elf` + 符号表 |
| **Android NDK r27c** | Google | 重新编译 `libdfroot.so`（bootstrap 修改后） | 新 `.so` |
| **Android build-tools 35** | Google | `zipalign` + `apksigner` 重签 APK | 可安装的 APK |
| **keytool** | JDK | 生成自签名证书 `dfroot.jks` | 签名密钥 |
| **DirtyFrag-vr 1.16-vr** | diabl0w / DONGDERS | 临时 root 引擎（CVE-2026-43284 page-cache 写） | 临时 uid=0 |
| **KernelSU 3.3.1** | tiann/KernelSU | 第一版持久 root（LKM 模式） | `init_boot` 补丁 |
| **SukiSU-Ultra 4.3.0-r2** | SukiSU-Ultra | 最终使用的管理器（`--block-module` 能力） | 最终 `init_boot` 补丁 |
| **payload 提取脚本** | 本仓库 `scripts/extract_payload.py` | 从 OTA `payload.bin` 提取 boot/init_boot/vendor_boot | 原厂镜像 |

---

## 3. 阶段一：侦察与可行性

### 做了什么

1. 读 DirtyFrag-vr 的运行日志，确认它改写了哪些文件：
   - `crash_dump64` ← `splicehelper`（page-cache 写入的落点）
   - `/vendor/lib64/libbinderdebug.so` ← `dfroot.ko`
   - `/system/lib64/libc++.so` ← shellcode + trampoline
   - hook 创建 `/dev/df`，并调用 `/vendor/bin/insmod` 加载模块
2. 解析本机内核配置（从 `Image` 里的 IKCFG 段）：
   - `CONFIG_MODVERSIONS=y`
   - `CONFIG_MODULE_SIG=y`，但 `CONFIG_MODULE_SIG_FORCE` **未开**
   - `CONFIG_MODULE_FORCE_LOAD` **未开**
3. 结论：模块没有 `__versions` 时，`check_version()` 会走 `try_to_force_load()`，因为 `FORCE_LOAD` 未开而返回 `-ENOEXEC`。

### 验证

```sh
# 模块加载失败的关键日志
insmod: failed to load ...: Exec format error
```

---

## 4. 阶段二：临时 root（DirtyFrag-vr 适配）

目标：在解锁前拿到一次 uid=0，用来写 `devinfo`。

### 4.1 从 OTA 提取原厂镜像

```sh
python scripts/extract_payload.py payload.bin boot        boot.img
python scripts/extract_payload.py payload.bin init_boot   init_boot.img
python scripts/extract_payload.py payload.bin vendor_boot vendor_boot.img
```

内核 `Image` 在 `boot.img` 偏移 4096，BTF 在 38,411,892。

### 4.2 恢复内核符号与 CRC

```sh
# 用 vmlinux-to-elf 从 Image 恢复符号
vmlinux-to-elf Image vmlinux.elf
```

注意：恢复出的符号基址是 `0xffffffc008000000`，而真实内核基址是 `0xffffffc080000000`，需要 **+0x78000000** 修正。

从导出符号表取出 12 个 CRC（本机实测）：

| 符号 | CRC |
|---|---|
| `module_layout` | `13af248c` |
| `snprintf` | `656e4a6e` |
| `register_kprobe` | `0472cf3b` |
| `_printk` | `92997ed8` |
| `unregister_kprobe` | `eb78b1ed` |
| `strcmp` | `e2d5255a` |
| `__ubsan_handle_cfi_check_fail_abort` | `df7a4c69` |
| `arm64_const_caps_ready` | `14b89635` |
| `cpu_hwcap_keys` | `d14fef22` |
| `cpu_hwcaps` | `77c1b75a` |
| `memset` | `dcb764ad` |
| `__stack_chk_fail` | `c2c193d2` |

### 4.3 重打 ko

对 `libdfroot.so` 里的目标 ko：

1. 用 `scripts/extract_kos.py` 拆出 8 个 ELF；
2. 用 `scripts/patch_ko.py`：
   - 新增 `__versions` 段（12 条 CRC，对应上面的表）；
   - 把 `.modinfo` 的 `vermagic` 改成设备内核完整字符串：
     `5.15.137-ge30fcc60efc0-dirty SMP preempt mod_unload modversions vivo aarch64`
3. 重新放回 `libdfroot.so`。

### 4.4 修改 bootstrap 并重编

改动点：

- `main()` 开头先 `dd` 出 `devinfo` 到 `/data/local/tmp/devinfo.img`；
- 如果存在 `/data/local/tmp/devinfo_patched.img`，写回 `devinfo` 并 `touch("/dev/dfunlock")`；
- `ksud late-load` 显式加 `--kmi android13-5.15`（vivo 内核串没有 `androidNN`，自动识别会失败）；
- 诊断输出写到 `/data/local/tmp`。

```sh
scripts/build_dfroot.ps1   # NDK r27c clang 编译
```

### 4.5 重签 APK

```sh
# 生成自签名证书（密码 dfroot）
keytool -genkeypair -keystore dfroot.jks -alias dfroot -keyalg RSA -keysize 2048 -validity 10000

zipalign -f -p 4 app-unsigned.apk app-aligned.apk
apksigner sign --ks dfroot.jks --ks-pass pass:dfroot --out dfroot-signed.apk app-aligned.apk
```

### 4.6 运行与验证

```sh
adb install -r dfroot-signed.apk
# 打开 App，等待 hook 完成
adb shell "su -c id"
# uid=0(root) ...
```

此时 `/proc/modules` 里能看到 `kernelsu`（临时 LKM）。

---

## 5. 阶段三：用 devinfo 解锁 bootloader

> 思路来源：酷安 @O5大帝 的 iQOO Neo7 竞速版教程，PD2227 的 devinfo 布局一致。

### 5.1 备份并修改 devinfo

```sh
dd if=/dev/block/by-name/devinfo of=/sdcard/devinfo.img bs=4096 count=1
```

原厂前 16 字节：

```
41 4e 44 52 4f 49 44 2d 42 4f 4f 54 21 00 00 01
A  N  D  R  O  I  D  -  B  O  O  T  !  .  .  .
```

把 **0x0D、0x0E 从 `00` 改成 `01`**，得到：

```
41 4e 44 52 4f 49 44 2d 42 4f 4f 54 21 01 01 01
```

即社区说的「`21 01 01 01`」。

```sh
dd if=/sdcard/devinfo_patched.img of=/dev/block/by-name/devinfo bs=4096 count=1
```

### 5.2 重启与验证

重启后手机会提示解锁/清除数据。之后：

```sh
fastboot oem device-info
# Device unlocked: true
# Device critical unlocked: true

getprop ro.boot.flash.locked      # 0
getprop ro.boot.verifiedbootstate # orange
```

> 代价：`/data` 被清空，设备进入 orange state，部分银行/DRM App 会检测到。

---

## 6. 阶段四：持久 root（KernelSU）

### 6.1 从 OTA 提取原厂 init_boot

```sh
python scripts/extract_payload.py payload.bin init_boot init_boot.img
```

本机 `init_boot.img`：8,388,608 字节，`ANDROID!`，header v4，`ramdisk_size=2,302,973`。

### 6.2 用管理器修补

1. 安装 KernelSU 管理器 APK；
2. 「安装」→「选择文件并修补」→ 选 `init_boot.img`；
3. KMI 必须手动选 **android13-5.15**（自动识别显示 `Unknown`）；
4. 产物：`/sdcard/Download/kernelsu_patched_*.img`（`ramdisk_size=2,799,533`）。

### 6.3 刷入并验证

```sh
adb reboot bootloader
fastboot flash init_boot kernelsu_patched_*.img
fastboot reboot
```

```sh
grep kernelsu /proc/modules
# kernelsu 217088 1 - Live ...

/system/bin/su -c id
# uid=0(root) ... context=u:r:ksu:s0
```

到「超级用户」里给 Shell 打开 Root 权限后，adb 的 `su` 才可用。

---

## 7. 阶段五：切换到 SukiSU（可选，但推荐）

KernelSU 3.3.1 在本机有两个问题：KMI 需要手动指定、模块页无限加载。换 SukiSU-Ultra：

1. 安装 `SukiSU_v4.3.0-r2_41150-release.apk`；
2. 「安装」→ 选 `init_boot.img` → KMI `android13-5.15` → 修补；
3. `fastboot flash init_boot kernelsu_patched_*.img`；
4. 开机验证「工作中 · LKM」与 `su`。

SukiSU 的 `ksud` 版本为 4.3.0-r2（uapi 6），支持 `boot-patch`、`--block-module` 等命令。

---

## 8. 阶段六：OTA 升级到 Android 15 并保留 root

### 8.1 确认 OTA 目标

```sh
unzip -p /data/ota_package/OTAPackage/*.zip META-INF/com/android/metadata
```

关键字段：

```
post-build=vivo/PD2227/PD2227:15/AP3A.240905.015.A2/...
post-version=PD2227_A_15.2.11.1.W10.V000L1
post-sdk-level=35
ota-type=AB
package-type=full
```

OTA 会写入**非当前槽**（本机 b → a），并把 a 槽的 `init_boot` 覆盖为原厂。

### 8.2 取出新槽的 init_boot

```sh
dd if=/dev/block/by-name/init_boot_a of=/sdcard/init_boot_a.img bs=4096
```

确认是新镜像（ramdisk 2,304,100，与旧的 2,302,973 不同）。

### 8.3 用当前 root 给新槽打补丁

新内核仍是 5.15（`5.15.178`），KMI 继续用 `android13-5.15`：

```sh
su -c '/data/adb/ksud boot-patch -b /sdcard/init_boot_a.img \
       --kmi android13-5.15 --partition init_boot \
       --block-module vr -o /sdcard/Download'
```

也可以直接用仓库脚本：

```sh
su -c 'sh /data/local/tmp/patch_inactive_slot.sh --block-vr'
```

### 8.4 重启前刷入目标槽

```sh
adb reboot bootloader
fastboot flash init_boot_a kernelsu_patched_*.img
fastboot reboot
```

### 8.5 验证

```sh
getprop ro.build.version.release   # 15
getprop ro.build.display.id        # PD2227C_A_15.2.11.1.W10
grep kernelsu /proc/modules        # Live
su -c id                           # uid=0(root) ... u:r:ksu:s0
```

### 8.6 回滚

旧槽（b）保留升级前系统与补丁：

```sh
fastboot set_active b
fastboot reboot
```

---

## 9. 阶段七：vr.ko 导致模块页无限加载（定位与修复）

### 现象

SukiSU/KernelSU 的「模块」页一直转圈；主页、超级用户正常。

### 诊断

1. adb root 下 `ksud module list` 秒回 `[]`；
2. 打开模块页时 dmesg 出现 `KernelSU: newfstatat su->ksud!`，ksud 进程一闪而过；
3. logcat 里 `kernelsu_zygote` 被 `SIGSYS (SYS_SECCOMP)` 杀掉；
4. `/proc/modules` 里 `vr 45056 0 [permanent]`。

**根因**：vr.ko 会给 App 起源任务打标记，并在其拿到 root 后于 `sys_exit` 杀掉；模块页的 root shell 刚拿到 root 就被杀，结果永远不返回。

### 修复

```sh
su -c '/data/adb/ksud boot-patch -b /sdcard/init_boot_a.img \
       --kmi android13-5.15 --partition init_boot \
       --block-module vr -o /sdcard/Download'
fastboot flash init_boot_a kernelsu_patched_*.img
```

验证：

```sh
grep -iE 'vr |kernelsu' /proc/modules
# 只有 kernelsu
```

模块页恢复正常，可安装/卸载模块。

> 详细版见 [`vr-ko-module-page-fix.md`](vr-ko-module-page-fix.md)。

---

## 10. 命令速查（按执行顺序）

```sh
# 0) 临时 root（DirtyFrag 适配版 APK）
adb install -r dfroot-signed.apk
su -c id

# 1) 解锁
dd if=/dev/block/by-name/devinfo of=/sdcard/devinfo.img bs=4096 count=1
# 改 0x0D/0x0E 为 01
dd if=/sdcard/devinfo_patched.img of=/dev/block/by-name/devinfo bs=4096 count=1
# 重启 → 清数据 → 验证 unlocked

# 2) 持久 root
python scripts/extract_payload.py payload.bin init_boot init_boot.img
# 管理器修补 init_boot（KMI android13-5.15）
fastboot flash init_boot kernelsu_patched_*.img
su -c id

# 3) OTA 后保留 root（非当前槽）
dd if=/dev/block/by-name/init_boot_a of=/sdcard/init_boot_a.img bs=4096
su -c '/data/adb/ksud boot-patch -b /sdcard/init_boot_a.img \
       --kmi android13-5.15 --partition init_boot --block-module vr -o /sdcard/Download'
fastboot flash init_boot_a kernelsu_patched_*.img
```

---

## 11. 踩过的坑与处理

| 问题 | 原因 | 处理 |
|---|---|---|
| `insmod: Exec format error` | ko 没有 `__versions`，`FORCE_LOAD` 未开 | 注入 12 条 CRC 的 `__versions` 段 |
| vermagic 不匹配 | 模块自带的 vermagic 与设备内核不同 | 改写 `.modinfo` 为设备完整 vermagic |
| KMI 显示 `Unknown` | vivo 内核串没有 `androidNN` 段 | 手动选 `android13-5.15` / 传 `--kmi` |
| `ksud late-load` 返回 0 但没加载 | 命令 daemon 化，退出码不代表成功 | 以 `/proc/modules` 是否出现 `kernelsu` 为准 |
| 模块页一直加载 | vr.ko 杀掉 App 起源的 root shell | `boot-patch --block-module vr` |
| 升级后 root 丢失 | OTA 覆盖新槽 `init_boot` | 重启前给新槽打补丁并刷入 |
| 解锁后设备黑屏/重启慢 | 解锁清数据 + orange state | 等待首次开机完成，属正常 |

---

## 12. 风险与回滚

- 解锁会**清空数据**，并让设备进入 orange state；部分银行/支付/DRM App 可能拒绝运行。
- 修改 `init_boot` 会破坏 AVB 校验链；解锁状态下可以启动，但不要在上锁状态刷入修改过的镜像。
- 原厂 `boot.img` / `init_boot.img` / `vendor_boot.img` 已从 OTA 提取，可随时 fastboot 刷回。
- 旧槽（升级前系统）保留，可用 `fastboot set_active b` 回滚。
- 屏蔽 vr 会削弱 vivo 的部分反 root 检测；如需恢复，刷回不带 `--block-module` 的补丁镜像。

---

## 13. 仓库内相关文件

- [`dirtyfrag-vr-adaptation.md`](dirtyfrag-vr-adaptation.md)：DirtyFrag 适配细节（ko/CRC/vermagic/APK 重签）
- [`vr-ko-module-page-fix.md`](vr-ko-module-page-fix.md)：vr.ko 根因与修复
- [`verified-offsets.md`](verified-offsets.md)：内核符号/结构偏移
- [`evidence.md`](evidence.md)：关键命令输出证据
- `scripts/`：payload 提取、ko 处理、CRC、APK 重打包、非当前槽补丁脚本
