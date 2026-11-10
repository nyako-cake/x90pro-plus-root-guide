# vivo X90 Pro+（PD2227）解锁 BL + 持久 KernelSU Root 实录

> 设备：vivo X90 Pro+（V2227A / PD2227，QTI SM8550）
> 系统：Android 15，`PD2227C_A_15.2.11.1.W10.V000L1`（原 Android 14 `PD2227_A_14.1.15.11`）
> 内核：`5.15.178-gf4fc3f9ca234-dirty`（原 `5.15.137-ge30fcc60efc0-dirty`）
> 结果：**bootloader 已解锁 + KernelSU/SukiSU LKM 持久 root（重启、OTA 升级后均保留）**

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

> 后续升级到 Android 15 并换用 SukiSU 后，`kernelsu` 模块大小为 561152，状态同样是 `Live`，`su` 仍返回 `u:r:ksu:s0`。

---

## 📖 完整过程（工具 / 方法 / 顺序）

按时间顺序的完整记录见 [`docs/full-root-walkthrough.md`](docs/full-root-walkthrough.md)：

- 阶段一：侦察与可行性（DirtyFrag 日志、内核配置）
- 阶段二：临时 root（DirtyFrag-vr 适配：ko 重打、CRC、vermagic、APK 重签）
- 阶段三：devinfo 解锁 bootloader
- 阶段四：KernelSU 持久 root（init_boot 补丁）
- 阶段五：切换 SukiSU
- 阶段六：OTA 升级 Android 15 并保留 root
- 阶段七：vr.ko 修复（模块页无限加载）

每个阶段都记录了「用了什么工具、做了什么、怎么验证、失败怎么处理」。

---

## 前置条件

- 手机能开启「USB 调试」，电脑有 adb / fastboot（platform-tools）。
- 准备好自己设备的**完整 OTA 包**（本仓库脚本从 `payload.bin` 提取 `boot.img` / `init_boot.img` / `vendor_boot.img`）。
- **备份数据**：解锁会清空 `/data`。
- 建议先关闭系统自动更新（OTA 会覆盖 `init_boot`，root 失效）。
- **目标基线**：如果你的机器已经升级到比 `PD2227_A_14.1.15.11` 更高的官方版本，先按[第零部分](#第零部分可选把系统降到目标基线downgrader)把它降回这个基线，再继续后面的解锁与 root。

---

## 第零部分（可选）：把系统降到目标基线（Downgrader）

> 本仓库的基线是 Android 14 `PD2227_A_14.1.15.11.W10.V000L1`。
> 如果设备已经在更新的官方版本上（如 15 / 16），可以用社区项目 [Chumor/Downgrader](https://github.com/Chumor/Downgrader) 查询并下载 vivo 官方降级包，先回到这个基线。

### 0.1 它做什么、不做什么

- **做**：读取设备信息、检测降级凭据，用凭据请求 vivo 服务（`sysupgrade.vivo.com.cn`）查询可用降级包，展示目标版本 / 大小 / SHA-256，并下载、校验后保存到应用内部存储；
- **不做**：它**不刷机**。真正安装要靠系统升级器的「本地升级」，或手动刷写。

### 0.2 流程

1. 安装 Downgrader APK（Releases 页），打开后确认「设备信息」与「降级凭据」正常；
2. 查询可用的降级包，选目标版本（本仓库为 `PD2227_A_14.1.15.11`）；
3. 下载并等待 SHA-256 校验通过；
4. 用系统升级器选择本地升级包安装，或按包内镜像手动刷入；
5. 降级完成后确认版本，再进入第一部分。

### 0.3 注意

- 跨大版本降级通常会**清空数据**，先备份；
- vivo 有 anti-rollback 限制，能否降取决于该降级包的签名与回滚标记，**不是任意版本都能降**；
- 降级会覆盖 `init_boot`，root 需要按第二部分重新做；
- 本仓库 `init_boot.img`（`d7b3e907…`）就是从 `14.1.15.11` 提取的，可用它核对基线版本。

---

## 第一部分：先获取临时 root（DirtyFrag 适配）

> 先有 uid=0，才能读写 `devinfo` 完成解锁；临时 root 是整条链路真正意义上的第一步。

原版 DirtyFrag-vr 在本机 `5.15.137` 上加载 ko 失败（`insmod: Exec format error`），原因是 ko 没有 `__versions`、vermagic 也不匹配。我们做了这些适配：

1. 从内核 `Image` 恢复 kallsyms 与导出符号（`vmlinux-to-elf` + `pyelftools`）；
2. 给 `dfroot.ko` 注入 12 条 `__versions`（CRC 取自本机内核），并改写 `.modinfo` 的 vermagic；
3. 修改 `bootstrap.c`（devinfo 备份/写回、`ksud late-load --kmi android13-5.15`），用 NDK 重编 `libdfroot.so`；
4. 替换 APK 内的 `.so`，`zipalign` + `apksigner` 重签后安装运行。

完成后 hook 会完成 page-cache 改写并加载临时 LKM。完整细节见 [`docs/dirtyfrag-vr-adaptation.md`](docs/dirtyfrag-vr-adaptation.md)。

验证：

```sh
su -c id
# uid=0(root) gid=0(root) ...
```

---

## 第二部分：用 devinfo 解锁 bootloader

> 思路来源：酷安 @O5大帝 的 iQOO Neo7 竞速版教程（[原帖](https://www.coolapk.com/feed/74900704)）。
> 实测在 PD2227 上同样有效，devinfo 布局一致。

> 前置：已完成第一部分，`su -c id` 返回 `uid=0`。

### 1. 备份并修改 devinfo

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

### 2. 重启

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

## 第三部分：KernelSU 持久 root

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

## 第四部分：OTA 升级（Android 14 → 15）后保留 root

> 2025-11 实测：系统 OTA 全量包（`PD2227_A_15.2.11.1`）会写入**非当前槽**（b → a），并把该槽的 `init_boot` 覆盖为原厂，root 会丢失。
> 只要在重启前把新槽的 `init_boot` 用当前 root 打好补丁再刷回去，就能带着 root 升级。

### 1. 确认 OTA 状态

```sh
getprop ro.boot.slot_suffix            # 当前槽，例如 _b
# OTA 包元数据里能看到目标版本（需要 root 读 /data/ota_package）
unzip -p /data/ota_package/OTAPackage/*.zip META-INF/com/android/metadata | grep -E 'post-build|post-version'
```

### 2. 取出非当前槽的原厂 init_boot

```sh
# 当前是 b，新系统在 a
dd if=/dev/block/by-name/init_boot_a of=/sdcard/init_boot_a.img bs=4096
```

核对头部是 `ANDROID!`、ramdisk 大小与旧版不同（说明是 OTA 写入的新镜像）。

### 3. 用当前 root 打补丁（顺便屏蔽 vr）

新内核仍是 5.15，KMI 继续选 `android13-5.15`；`--block-module vr` 顺带解决模块页问题（见附录 C）：

```sh
su -c '/data/adb/ksud boot-patch -b /sdcard/init_boot_a.img \
       --kmi android13-5.15 --partition init_boot \
       --block-module vr -o /sdcard/Download'
```

### 4. 重启前刷入目标槽

```sh
adb reboot bootloader
fastboot flash init_boot_a kernelsu_patched_*.img
fastboot reboot
```

### 5. 验证

```sh
getprop ro.build.version.release        # 15
getprop ro.build.display.id             # PD2227C_A_15.2.11.1.W10
grep kernelsu /proc/modules             # Live
su -c id                                # uid=0(root) ... u:r:ksu:s0
```

### 6. 回滚

旧槽（b）仍保留升级前的系统与补丁，必要时：

```sh
fastboot set_active b
fastboot reboot
```

---

## 工具脚本

| 脚本 | 用途 |
|---|---|
| `scripts/extract_payload.py` | 从 OTA `payload.bin` 提取 boot / init_boot / vendor_boot |
| `scripts/vendor_boot_tool.py` | 解析 vendor_boot v3/v4、解压 LZ4 legacy、列出/查找 cpio 里的 `vr.ko` 等 |
| `scripts/patch_inactive_slot.sh` | 给非当前槽的 `init_boot` 打 SukiSU 补丁（`--block-vr` 可选），用于 OTA 后保留 root |
| `scripts/extract_kos.py` / `patch_ko.py` / `repack_apk.py` | DirtyFrag 的 ko 提取 / 打补丁 / APK 重打包 |

本次操作涉及的镜像哈希、检测器日志位置见 [`docs/session-artifacts.md`](docs/session-artifacts.md)。

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

- **vr.ko（已解决）**：vivo 的反 root 模块会在 `sys_exit` 杀掉「App 起源且已拿到 root」的进程，导致 KernelSU/SukiSU 的「模块」页无限加载（`ksud module list` 的 root shell 被杀）。用 `ksud boot-patch --block-module vr` 把 vr 在内核启动时屏蔽即可，详见 [`docs/vr-ko-module-page-fix.md`](docs/vr-ko-module-page-fix.md)。
- **OTA**：系统更新会覆盖新槽的 `init_boot`，root 丢失；按[第四部分](#第四部分ota-升级android-14--15后保留-root)的做法可以在升级前把新槽补丁刷入，升级后 root 仍在。部分更新可能重新锁定 BL。
- **KMI**：vivo 内核串不含 `androidNN`，KernelSU/SukiSU 修补时必须手动选 `android13-5.15`（5.15 内核升级到 5.15.178 后仍然如此）。

---

## 致谢

- devinfo 解锁思路：[酷安 @O5大帝](https://www.coolapk.com/feed/74900704)
- 临时 root 引擎：[diabl0w/DFRoot](https://github.com/diabl0w/DFRoot)、[DONGDERS/DirtyFalg-vr](https://github.com/DONGDERS/DirtyFalg-vr)
- Root 方案：[tiann/KernelSU](https://github.com/tiann/KernelSU)、[SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra)（LKM + `--block-module`）
- 内核符号恢复：[vmlinux-to-elf](https://github.com/marin-m/vmlinux-to-elf)

## 许可

- 文档：CC BY 4.0
- 脚本：MIT
