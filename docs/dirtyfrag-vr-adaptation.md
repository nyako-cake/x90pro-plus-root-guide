# DirtyFrag-vr 在 PD2227（5.15.137）上的适配记录

本文是 [DirtyFrag-vr](https://github.com/DONGDERS/DirtyFalg-vr)（基于 DFRoot 的
临时 root 工具）在 vivo X90 Pro+ 上的完整适配过程。原版直接运行会停在：

```
libc++: loading custom module
timeout: ERROR - check logcat & dmesg
```

适配后可以走完整条链：

```
kernel module: launching bootstrap
bootstrap: starting SU daemon
ksud start: SUCCESS
```

---

## 1. 原版为什么失败

DirtyFrag 把 8 个按 KMI 预编译的 `dfroot-*.ko` 用 `.incbin` 嵌进
`libdfroot.so`，运行时把对应 KMI 的 ko 写进
`/vendor/lib64/libbinderdebug.so` 的 page cache，再由 libc++ 钩子
`execve("/vendor/bin/insmod", ...)`。

在 PD2227 上（内核 `5.15.137-ge30fcc60efc0-dirty`）有两个问题：

1. **模块没有符号版本表**
   从 APK 里拆出来的 android13-5.15 ko，`__versions` 段大小为 **0**；
   而本机内核 `CONFIG_MODVERSIONS=y`、`CONFIG_MODULE_FORCE_LOAD` 未开。
   5.15 的 `check_modstruct_version()` 会对 `module_layout` 调用
   `check_version()`，模块没有 `__versions` 时走 `try_to_force_load()`，
   直接返回 `-ENOEXEC`——连 ko 的 init 都不会执行。

2. **vermagic 不匹配**
   ko 的 vermagic 是
   `5.15.202-android13-5.15.202_r00-dirty SMP preempt mod_unload modversions aarch64`，
   本机是
   `5.15.137-ge30fcc60efc0-dirty SMP preempt mod_unload modversions vivo aarch64`。

所以只改 vermagic 不够，必须**补一份 CRC 正确的 `__versions`**。

---

## 2. 从 OTA 内核拿数据

```sh
python scripts/extract_payload.py payload.bin boot boot.img
# boot.img 头部：header v4，kernel 在 0x1000 处，Image 为未压缩 aarch64 Image
```

用 [vmlinux-to-elf](https://github.com/marin-m/vmlinux-to-elf) 恢复符号表：

```sh
vmlinux-to-elf --base-address 0xffffffc080000000 Image vmlinux.elf
```

> 该工具输出的符号值可能以另一个基址（本机是 `0xffffffc008000000`）计算，
> 与段地址差 `0x78000000`；`kernel_crcs.py` 的 `--symbol-shift` 就是为此。

解析内核导出表（`__ksymtab` + `__kcrctab`）拿 CRC：

```sh
python scripts/kernel_crcs.py vmlinux.elf --out crcs.json \
  --symbols module_layout,snprintf,register_kprobe,_printk,unregister_kprobe,strcmp,__ubsan_handle_cfi_check_fail_abort,arm64_const_caps_ready,cpu_hwcap_keys,cpu_hwcaps,memset,__stack_chk_fail
```

本机结果：

| 符号 | CRC |
|---|---|
| `module_layout` | `0x13af248c` |
| `snprintf` | `0x656e4a6e` |
| `register_kprobe` | `0x0472cf3b` |
| `_printk` | `0x92997ed8` |
| `unregister_kprobe` | `0xeb78b1ed` |
| `strcmp` | `0xe2d5255a` |
| `__ubsan_handle_cfi_check_fail_abort` | `0xdf7a4c69` |
| `arm64_const_caps_ready` | `0x14b89635` |
| `cpu_hwcap_keys` | `0xd14fef22` |
| `cpu_hwcaps` | `0x77c1b75a` |
| `memset` | `0xdcb764ad` |
| `__stack_chk_fail` | `0xc2c193d2` |

---

## 3. 拆出并修补 ko

```sh
python scripts/extract_kos.py libdfroot.so kos/
```

会按 vermagic 命名得到 8 个文件；本机用到 `dfroot-android13-5.15.ko`。

```sh
python scripts/patch_ko.py kos/dfroot-android13-5.15.ko \
  --crcs crcs.json \
  --vermagic "5.15.137-ge30fcc60efc0-dirty SMP preempt mod_unload modversions vivo aarch64" \
  --out kos-patched/dfroot-android13-5.15.ko
```

`patch_ko.py` 做两件事：

- 重写 `.modinfo` 里的 `vermagic=`；
- 把空的 `__versions` 段指向文件末尾新追加的 12 条
  `struct modversion_info { char name[56]; unsigned long crc; }`。

> 注意：section header 要指向新数据且 `sh_size = 12 * 64`，否则内核仍然
> 认为没有版本表。

---

## 4. 重编 libdfroot.so

ko 大小变化后 `.incbin` 布局变了，必须重编 `libdfroot.so`（它其实是
一个 PIE 可执行文件，名字以 `lib` 开头只是为了被 APK 打包）。

```powershell
$env:NDK = "C:\android-ndk-r27c"
.\scripts\build_dfroot.ps1 -Source <DirtyFrag jni 目录> -OutDir .\build
```

然后把新的 `.so` 换进 APK：

```sh
python scripts/repack_apk.py DirtyFrag.apk DirtyFrag-new.apk \
  lib/arm64-v8a/libdfroot.so=build/libdfroot.so
zipalign -f 4 DirtyFrag-new.apk DirtyFrag-aligned.apk
apksigner sign --ks dfroot.jks --out DirtyFrag-signed.apk DirtyFrag-aligned.apk
adb install -r DirtyFrag-signed.apk   # 签名变了，需先卸载旧版
```

---

## 5. bootstrap.c 的 KMI 修复（最关键的一步）

`dfroot.ko` 只是"启动器"，SU 守护进程由 bootstrap 通过
`ksud late-load` 拉起。KernelSU 的 KMI 自动识别依赖内核版本串里的
`androidNN` 段，而 vivo 的串是 `5.15.137-ge30fcc60efc0-dirty`，
识别结果是 `Unknown`，daemon 随后静默失败（`late-load` 会 daemonize，
父进程返回 0，看起来像成功）。

修复：显式传 KMI。

```c
run_ctx(NULL, (char *[]){
    KSUD_STAGE, "late-load",
    "--package-name", su_manager,
    "--kmi", "android13-5.15",
    NULL
});
```

完整改动见 [patches/README.md](../patches/README.md)。

---

## 6. 验证

`/proc/modules` 在成功时应出现 `dfroot`（模块跑完会自行卸载，也可能一闪而过，
所以更可靠的是看 App 日志的 `ksud start: SUCCESS`）。

内核日志（由 ko 自己落盘）：

```
dfroot: cleared page cache for crash_dump64
dfroot: selinux_state permissive
dfroot: W1c vr sys_exit probe disarmed (funcs=NULL, off=64, btf)
dfroot: usermodehelper_exec returned 0
```

App 日志：

```
kernel module: launching bootstrap
bootstrap: starting SU daemon
ksud start: SUCCESS
```

此时 SELinux 变为 Permissive，KernelSU 处于“工作中 [越狱模式]”。

---

## 7. 许可与分发

DirtyFrag/DFRoot 是 GPL-2.0。本仓库**不包含**修改后的 ko、APK 或厂商镜像，
只提供脚本与步骤；如果你想分发修改版 APK，请同时提供对应源码并遵守 GPL。
