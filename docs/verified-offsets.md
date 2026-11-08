# PD2227 / 5.15.137 实测数据

以下数值由本机 OTA 内核（`boot.img` → `Image`）离线解析得到，并与设备上 GhostLock 的 profile 交叉核对过。

## 设备

| 项 | 值 |
|---|---|
| 型号 | vivo X90 Pro+（V2227A / PD2227） |
| SoC | QTI SM8550 |
| 系统 | PD2227_A_14.1.15.11.W10.V000L1（Android 14，安全补丁 2024-09-01） |
| 内核 | `5.15.137-ge30fcc60efc0-dirty` |
| vermagic | `5.15.137-ge30fcc60efc0-dirty SMP preempt mod_unload modversions vivo aarch64` |
| KMI | `android13-5.15`（内核串里没有 `androidNN` 段，需手动指定） |

## BTF：task_struct / cred

| 字段 | 偏移 |
|---|---|
| `thread_info` | 0 |
| `task_struct.real_cred` | 1936（0x790） |
| `task_struct.cred` | 1944（0x798） |
| `task_struct.comm` | 1960（0x7a8） |
| `cred.usage` | 0 |
| `cred.uid` | 4 |
| `cred.gid` | 8 |
| `cred.cap_permitted` | 48 |
| `cred.security` | 120 |
| `cred.user` | 128 |
| `cred.user_ns` | 136 |
| `cred.group_info` | 152 |

## 内核导出符号（本机 `__kcrctab`）

DirtyFrag android13-5.15 模块需要的 12 个符号，全部存在：

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

## GhostLock profile（同一台机器，供对照）

| 项 | 值 |
|---|---|
| `init_cred` | `0x2e2a6f8` |
| `init_task` | `0x2e72700` |
| `root_task_group` | `0x2f84b40` |
| `selinux_state`（enforcing 首字节） | `0x30b5f80` |
| `__tracepoint_sys_exit` | `0x2f0c7c8` |
| `struct tracepoint.funcs` | 64 |
| `p0 kernel_phys_load` | `0xa8000000` |
| `p0 delta` | `0x28000000` |

## devinfo

```
00000000  41 4e 44 52 4f 49 44 2d 42 4f 4f 54 21 00 00 01
          A  N  D  R  O  I  D  -  B  O  O  T  !  -- -- --
```

- `0x0D`、`0x0E`：解锁标记（`00 00` → `01 01` 后 bootloader 解锁）；
- `0x0F`：本机原厂即为 `01`；
- 写入后前 16 字节应为 `… 21 01 01 01`。
