# vivo X90 Pro+（PD2227）解锁 BL + 持久 KernelSU Root 实录

> 设备：vivo X90 Pro+（V2227A / PD2227，QTI SM8550）
> 系统：PD2227_A_14.1.15.11.W10.V000L1（Android 14）
> 内核：5.15.137-ge30fcc60efc0-dirty
> 结果：**bootloader 已解锁 + KernelSU LKM 持久 root（重启不丢）**

---

## ⚠️ 免责声明

- 本仓库记录的是**对自己设备**的折腾过程，**会清空数据、可能变砖、失去保修**，并影响银行/支付类 App 的安全环境。
- 解锁 bootloader 后设备进入 orange state，部分 App 会检测到。
- 所有操作风险自负；请先完整备份，并确认你能接受设备变砖。
- 仓库不包含任何厂商固件、签名密钥或个人信息；镜像请从你自己的 OTA 包提取。

---

## 成果

```
$ grep -i kernelsu /proc/modules
kernelsu 217088 0 - Live 0x0000000000000000 (OE)

$ getenforce
Enforcing

$ /system/bin/su -c id
uid=0(root) gid=0(root) groups=0(root) context=u:r:ksu:s0
```

重启后依旧有效（KSU 通过修补过的 `init_boot` 开机加载）。

---

## 前置条件

- 手机能开启「USB 调试」，电脑有 adb / fastboot（platform-tools）。
- 准备好自己设备的**完整 OTA 包**（本仓库脚本从 `payload.bin` 提取 `boot.img` / `init_boot.img` / `vendor_boot.img`）。
- **备份数据**：解锁会清空 `/data`。
- 建议先关闭系统自动更新（OTA 会覆盖 `init_boot`，root 失效）。

---

## 第一部分：用 devinfo 解锁 bootloader

> 思路来源：酷安 @O5大帝 的 iQOO Neo7 竞速版教程（[原帖](https://www.coolapk.com/feed/74900704)）。
> 实测在 PD2227 上同样有效，devinfo 布局一致。

### 1. 先拿到临时 root

解锁 devinfo 需要 root 权限读写块设备。任选一种临时 root 方式（本仓库附录 A 记录了 DirtyFrag 的适配过程）。

验证：

```sh
su -c id    # uid=0
```

### 2. 备份并修改 devinfo

```sh
# 备份（4 KB）
dd if=/dev/block/by-name/devinfo of=/sdcard/devinfo.img bs=4096 count=1

# 十六进制查看
# 正常内容应为：
# 00000000  41 4e 44 52 4f 49 44 2d 42 4f 4f 54 21 00 00 01  ANDROID-BOOT!...
```

把 **0x0D、0x0E 两个字节从 `00` 改成 `01`**，改完前 16 字节应为：

```
41 4e 44 52 4f 49 44 2d 42 4f 4f 54 21 01 01 01
```

即教程里说的「`21 01 01 01`」。

```sh
# 写回
dd if=/sdcard/devinfo_patched.img of=/dev/block/by-name/devinfo bs=4096 count=1
```

### 3. 重启

重启后手机会提示解锁/清除数据，按提示确认；随后进入系统。验证：

```sh
fastboot oem device-info
# (bootloader) Device unlocked: true
# (bootloader) Device critical unlocked: true
```

系统内：

```sh
getprop ro.boot.flash.locked   # 0
getprop ro.boot.verifiedbootstate  # orange
```

---

## 第二部分：KernelSU 持久 root

### 1. 从 OTA 提取原厂镜像

```sh
python scripts/extract_payload.py payload.bin boot        boot.img
python scripts/extract_payload.py payload.bin init_boot   init_boot.img
python scripts/extract_payload.py payload.bin vendor_boot vendor_boot.img
```

### 2. 用 KernelSU 管理器修补 init_boot

1. 安装 [KernelSU](https://github.com/tiann/KernelSU/releases) 管理器 APK；
2. 打开「安装」→「选择文件并修补」→ 选 `init_boot.img`；
3. KMI 选择 **android13-5.15**（vivo 内核版本串里没有 `androidNN` 段，自动识别会显示 `Unknown`，必须手动选）；
4. 修补完成后，产物在 `/sdcard/Download/kernelsu_patched_*.img`。

### 3. fastboot 刷入

```sh
adb reboot bootloader
fastboot flash init_boot kernelsu_patched_2026xxxx_xxxxxx.img
fastboot reboot
```

> 本机为 A/B 设备，`fastboot flash init_boot` 会自动写入当前 slot（`_b`）。

### 4. 授权

开机后 KernelSU 显示「工作中 · LKM」。到「超级用户」里给需要的 App（如 Shell、文件管理器）打开 Root 权限，然后：

```sh
/system/bin/su -c id
# uid=0(root) ... context=u:r:ksu:s0
```

### 5. 验证持久性

重启一次，重复上面的 `grep kernelsu /proc/modules` 与 `su -c id`。

---

## 附录 A：临时 root / DirtyFrag 适配（不刷机路线）

> 完整步骤、CRC 表和命令见 [`docs/dirtyfrag-vr-adaptation.md`](docs/dirtyfrag-vr-adaptation.md)。

在解锁前，我们用 DirtyFrag-vr 的临时 root 拿到了写 devinfo 的权限。原版在 5.15.137 上会卡在 `libc++: loading custom module`，原因与修复如下。

### A.1 失败原因

1. `dfroot.ko` 内嵌的 android13-5.15 模块：
   - `__versions` 段为 **0 字节**，没有符号 CRC；
   - vermagic 是 `5.15.202-android13-5.15.202_r00-dirty ...`。
2. 本机内核：
   - `CONFIG_MODVERSIONS=y`、`CONFIG_MODULE_FORCE_LOAD` 未开 → 没有 `__versions` 会在 `module_layout` 检查阶段被 `-ENOEXEC` 拒绝；
   - vermagic 为 `5.15.137-ge30fcc60efc0-dirty SMP preempt mod_unload modversions vivo aarch64`。

### A.2 修复

1. 从内核 `Image` 恢复符号表与导出表 CRC（见 `scripts/`，依赖 `vmlinux-to-elf` + `pyelftools`）；
2. 取出 APK 里内嵌的 ko（`libdfroot.so` 中 8 个 ELF），给目标 ko：
   - 写入 12 条 `__versions`（`module_layout` + 11 个未定义符号，CRC 取自设备内核）；
   - 改写 `.modinfo` 的 vermagic 为设备内核的完整字符串；
3. 用 NDK 重新编译 `libdfroot.so`（替换 ko 后 `.incbin` 大小变化），替换进 APK 并重新签名；
4. 修改 `bootstrap.c`：`ksud late-load` 增加 `--kmi android13-5.15`。

   > KSU 的 KMI 自动识别会解析内核版本串里的 `androidNN`，vivo 的串没有该段，daemon 会静默失败；显式传 `--kmi` 后 LKM 成功加载。

### A.3 参考脚本

- `scripts/extract_kos.py`：从 `libdfroot.so` 拆出 8 个 ko；
- `scripts/patch_ko.py`：写 `__versions` + 改 vermagic；
- `scripts/repack_apk.py`：替换 `.so` 并重新打包；
- `scripts/build_dfroot.ps1`：NDK 编译命令。

---

## 附录 B：救砖 / 回滚

- 原厂镜像已从 OTA 提取（`boot.img` / `init_boot.img` / `vendor_boot.img`），BL 解锁状态下可随时：

  ```sh
  fastboot flash init_boot init_boot.img
  fastboot flash boot      boot.img
  fastboot flash vendor_boot vendor_boot.img
  ```

- devinfo 也可回滚（写回 `devinfo.img` 原厂 4 KB），但**不会重新上锁**（解锁状态由安全启动状态机决定）。
- 若只是 OTA 后 root 失效：重新用管理器修补新的 `init_boot` 再刷入即可。

---

## 附录 C：已知问题

- **vr.ko**：vivo 的反 root 模块仍在 `vendor_boot`/`vendor_dlkm` 中；目前 KernelSU 可以共存，若出现管理器被杀、黑屏等，需要按社区方案处理 `vendor_boot` 中的 `vr.ko`。
- **OTA**：系统更新会覆盖 `init_boot`，root 丢失；更新后需重新修补。部分更新可能重新锁定 BL。
- **KMI**：vivo 内核串不含 `androidNN`，KernelSU 修补时必须手动选 `android13-5.15`。

---

## 致谢

- devinfo 解锁思路：[酷安 @O5大帝](https://www.coolapk.com/feed/74900704)
- 临时 root 引擎：[diabl0w/DFRoot](https://github.com/diabl0w/DFRoot)、[DONGDERS/DirtyFalg-vr](https://github.com/DONGDERS/DirtyFalg-vr)
- Root 方案：[tiann/KernelSU](https://github.com/tiann/KernelSU)
- 内核符号恢复：[vmlinux-to-elf](https://github.com/marin-m/vmlinux-to-elf)

## 许可

- 文档：CC BY 4.0
- 脚本：MIT
