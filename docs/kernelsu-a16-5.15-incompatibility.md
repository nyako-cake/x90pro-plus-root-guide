# KernelSU 3.3.1 在 Android 16 + vivo 5.15 内核上无法启动（PD2227 实测）

> 设备：vivo X90 Pro+（PD2227 / V2227A，SM8550）
> 系统：`PD2227C_A_16.3.14.0.W10`（Android 16 / SDK 36）
> 内核：`5.15.197-g346b1c36bd5c-dirty`
> 管理器：KernelSU v3.3.1（32680），LKM 模式
> 结果：**无法启动**（卡在启动早期，adb/fastboot 都消失）；SukiSU 4.3.0-r2 可正常使用

---

## 现象

用 KernelSU 3.3.1 给 `init_boot` 打补丁并刷入后：

- 开机卡住，`adb devices` 和 `fastboot devices` 都看不到设备；
- 有时会回落到 fastboot，有时需要长按电源键强制重启；
- 刷回 SukiSU 镜像或原厂 `init_boot` 即可恢复。

---

## 三次尝试

| # | 做法 | 结果 |
|---|---|---|
| 1 | 从 OTA `payload.bin` 提取**原厂** A16 `init_boot`，用 `ksud boot-patch --kmi android13-5.15 --block-module vr` 打补丁后刷入 | 卡启动 |
| 2 | 从 SukiSU 镜像重建“原厂 ramdisk”，再打 KSU 补丁 | 卡启动 |
| 3 | 直接在 SukiSU 已打补丁的镜像上再打 KSU 补丁 | 卡启动 |

三次都排除“镜像打包错误”的可能：原厂镜像、重建镜像、已启动过的 SukiSU 镜像都试过，结果一致。

---

## 原因分析

### 1. KernelSU 官方 KMI 矩阵里没有 `android16-5.15`

KernelSU 按 KMI 发布预编译 LKM（v3.3.1 资产）：

| Android | KMI |
|---|---|
| 13 | `android13-5.10`、`android13-5.15` |
| 14 | `android14-5.15`、`android14-6.1` |
| 15 | `android15-6.6` |
| 16 | **`android16-6.12`** |
| 17 | `android17-6.18` |

这台机器是 **Android 16 + 5.15 内核**，只能退回用 `android13-5.15` 的 LKM——它是给 Android 13 时代的 GKI 5.15 内核编译的。

### 2. vermagic 对不上

```
设备内核（/proc/version）：
5.15.197-g346b1c36bd5c-dirty SMP preempt mod_unload modversions vivo aarch64

KernelSU 3.3.1 的 android13-5.15 LKM：
5.15.202-android13-5.15.202_r00-dirty SMP preempt mod_unload modversions aarch64
```

- 内核版本号不同：197 vs 202
- 内核带 `vivo` 标记，模块是纯 GKI
- `CONFIG_MODVERSIONS=y`：模块的符号 CRC 来自 GKI 5.15.202，vivo 内核的导出符号 CRC 是另一套（vivo 加了 vendor hook / 私有符号）

`check_version()` 阶段就会失败。

### 3. ksuinit 没有回退到真实 init

从现象看，模块加载失败后 `ksuinit` 没有回退执行真实 `init`，而是卡住，导致系统连 adb/fastboot 都起不来。

---

## 为什么 SukiSU 可以

SukiSU 4.3.0-r2 的 LKM vermagic 同样是 `5.15.202-android13-5.15.202_r00`，但它能加载：

| | KernelSU 3.3.1 | SukiSU 4.3.0-r2 |
|---|---|---|
| LKM 大小 | 397,792 字节 | 671,360 字节 |
| 符号处理 | 直接引用 GKI 符号/CRC | 更偏向运行时解析（kallsyms/kprobe），对 vendor 内核容忍度高 |
| ksuinit | 失败后卡住 | 有回退/兼容处理 |
| 发布 | 2026-10 | 2026-11，针对新内核修过 |

结论：SukiSU 是**对非 GKI vendor 内核做过兼容**的分支；KernelSU 官方只保证 GKI 内核。

---

## 恢复方法

进 fastboot 后刷回可用镜像：

```sh
fastboot flash init_boot_b init_boot_b_a16_sukisu.img
fastboot reboot
```

或刷原厂（无 root）：

```sh
fastboot flash init_boot_b init_boot_a16_stock.img
```

验证：

```sh
adb shell getprop ro.build.display.id     # PD2227C_A_16.3.14.0.W10
adb shell grep kernelsu /proc/modules     # 只有 SukiSU 才有
adb shell su -c id
```

---

## 建议

- 在这台机器上继续使用 **SukiSU**（当前验证可用）；
- 等 KernelSU 上游增加 `android16-5.15` / vendor 兼容，或自行编译 LKM（需要 vivo 5.15.197 内核源码与符号表，成本高）；
- 关注 SukiSU / KowSU 等对 vendor 内核更友好的分支。

---

## 相关

- KernelSU Releases：<https://github.com/tiann/KernelSU/releases>
- SukiSU-Ultra：<https://github.com/SukiSU-Ultra/SukiSU-Ultra>
- 本仓库的 vr.ko 问题：[`vr-ko-module-page-fix.md`](vr-ko-module-page-fix.md)
