# vivo 机型 KernelSU/SukiSU「模块」页无限加载：根因与修复（vr.ko）

> 实测设备：vivo X90 Pro+（V2227A / PD2227，SM8550）
> 系统：Android 15，`PD2227C_A_15.2.11.1.W10.V000L1`
> 内核：`5.15.178-gf4fc3f9ca234-dirty`
> 管理器：SukiSU-Ultra v4.3.0-r2（41150-6），LKM 模式
> 现象版本：KernelSU 3.3.1（32680-5）与 SukiSU 4.3.0-r2 均可复现

---

## 现象

管理器主页显示「工作中 · LKM」、`su` 正常，但「模块」页一直转圈，模块列表永远加载不出来；「超级用户」「设置」正常。

同一现象在 Android 14 + KernelSU 3.3.1 上已出现，换到 SukiSU 后依旧，说明不是某一个管理器分支的问题。

---

## 诊断

### 1. adb root 下 ksud 完全正常

```sh
$ su -c '/data/adb/ksud module list'
[]
```

### 2. 模块页拉起 ksud 后进程一闪而过

打开模块页时，`ps` 里没有常驻的 `ksud`/`su`，但 dmesg 能看到 KSU 拦截 `su` 并拉起 ksud：

```
KernelSU: newfstatat su->ksud!
KernelSU: faccessat su->ksud!
```

随后 ksud 进程很快消失。

### 3. App 侧 root 桥接进程被 seccomp 杀掉

logcat 里能看到 `kernelsu_zygote` 死于 SIGSYS：

```
F libc: Fatal signal 31 (SIGSYS), code 1 (SYS_SECCOMP), syscall 146
      in tid ... (kernelsu_zygote)
```

### 4. vr.ko 常驻

```
$ grep vr /proc/modules
vr 45056 0 [permanent], Live 0x0000000000000000 (E)
```

---

## 根因

vivo 的 `vr.ko` 会给「App 起源」的任务打标记，并在这些任务拿到 root 后、于 `sys_exit` 探针里把它们杀掉。

管理器的「模块」页正是通过 **App 进程 fork 出的 root shell** 去执行 `ksud module list` 的：shell 刚拿到 root 就被 vr 杀掉，libsu 永远等不到退出结果，UI 就一直 loading。

这也解释了为什么 adb shell（非 App 起源、`Seccomp: 0`）里 `su` 一切正常，而 App 内的 root shell 全部失效。

---

## 修复

不需要改 `vendor_boot`。SukiSU 的 `boot-patch` 支持 `--block-module`（对应 [tiann/KernelSU#3655](https://github.com/tiann/KernelSU/pull/3655) 的模块加载过滤能力），把 vr 在内核启动时屏蔽掉：

```sh
su -c '/data/adb/ksud boot-patch -b /sdcard/init_boot_a.img \
       --kmi android13-5.15 --partition init_boot \
       --block-module vr -o /sdcard/Download'
```

产物刷入对应槽位：

```sh
fastboot flash init_boot_a kernelsu_patched_*.img
```

输出里会看到：

```
- Blocking modules: vr
- ksu_config content: "block_modules=vr bundled=1"
```

### 验证

```
$ grep -iE 'vr |kernelsu' /proc/modules
kernelsu 561152 1 - Live 0x0000000000000000 (OE)   # vr 已不再加载

$ su -c id
uid=0(root) gid=0(root) groups=0(root) context=u:r:ksu:s0
```

模块页恢复正常，可看到已安装模块列表，安装/卸载/启用均可用。

### 备选方案

修改 `vendor_boot` 的 vendor ramdisk，删除：

- `lib/modules/vr.ko`
- `lib/modules/5.15-gki/vr.ko`
- `modules.load` / `modules.load.recovery` 里的 `vr.ko` 行
- `modules.dep` 里的 `/lib/modules/.../vr.ko:` 条目
- `modules.softdep` 里的 `softdep vr pre: ...` 行

`--block-module` 更简单、可回滚，推荐优先使用。

---

## 副作用与注意事项

- 屏蔽的是 vivo 的反 root 模块，可能让 i管家/部分安全检测变弱；相机、手电筒、支付类 App 暂未发现异常。
- 配置写在 `init_boot` 的 `ksu_config` 里（`block_modules=vr`），**OTA 覆盖 `init_boot` 后需要重做**。
- 只对当前槽位生效；切回旧槽位时 vr 仍会加载。
- 如需恢复，刷回不带 `--block-module` 的补丁镜像即可。

---

## 上游同步

- SukiSU-Ultra 设备报告：[SukiSU-Ultra/SukiSU-Ultra#1043](https://github.com/SukiSU-Ultra/SukiSU-Ultra/issues/1043)
- KernelSU 能力来源：[tiann/KernelSU#3655](https://github.com/tiann/KernelSU/pull/3655)
