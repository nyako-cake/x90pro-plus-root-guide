# 关键输出摘录

以下为实测时的关键输出（已去掉序列号等个人信息）。

## 解锁后

```
$ fastboot oem device-info
(bootloader) Verity mode: true
(bootloader) Device unlocked: true
(bootloader) Device critical unlocked: true
(bootloader) Charger screen enabled: true
```

```
$ getprop ro.boot.flash.locked
0
$ getprop ro.boot.verifiedbootstate
orange
```

## 临时 root：dfroot.ko 成功装载

```
dfroot: cleared page cache for crash_dump64
dfroot: selinux_state permissive
dfroot: oplus_exe_block_ret_handler not found, skipping
dfroot: oplus_root_check_post_handler not found, skipping
dfroot: task_defex_enforce not found, skipping
dfroot: task_defex_user_exec not found, skipping
dfroot: W1c vr sys_exit probe disarmed (funcs=NULL, off=64, btf)
dfroot: usermodehelper_exec returned 0
```

## KernelSU 修补 init_boot

```
- Bootdevice: /data/data/me.weishu.kernelsu/cache/boot.img
- Preparing assets
- Unpacking boot image
- KMI: android13-5.15
- Adding KernelSU LKM
- Adding bundled LKM config
- Repacking boot image
- Output file is written to /storage/emulated/0/Download/kernelsu_patched_20261108_084630.img
- Done!
```

## 持久 root

```
$ grep -i kernelsu /proc/modules
kernelsu 217088 0 - Live 0x0000000000000000 (OE)

$ getenforce
Enforcing

$ /system/bin/su -c id
uid=0(root) gid=0(root) groups=0(root) context=u:r:ksu:s0
```

## KMI 自动识别失败的现象

```
选择 KMI
本设备 KMI 版本: Unknown
```

此时必须手动选择 `android13-5.15`。
