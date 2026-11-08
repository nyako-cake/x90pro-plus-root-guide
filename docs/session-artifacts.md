# 本次操作涉及的产物清单（2026-11-08）

> 本文只记录**文件身份**（大小 + SHA-256）与用途，**不包含任何厂商固件本体**。
> 镜像请从你自己的 OTA 包提取，或用下面的哈希核对本地备份是否一致。

---

## 一、启动镜像（本地备份）

| 文件 | 大小（字节） | SHA-256 | 说明 |
|---|---:|---|---|
| `init_boot.img` | 8,388,608 | `d7b3e90702a956ec1b0c3f757ae8e9497b2ac09b08121180025088a18da1b123` | Android 14 原厂 `init_boot`（从 OTA `payload.bin` 提取） |
| `boot.img` | 100,663,296 | `64a47499f18a7adb761b67c1c4f106788f867b9a9fb800aaaf5c4b75e8730455` | Android 14 原厂 `boot` |
| `vendor_boot.img` | 134,217,728 | `ec811e9e621f9c4430f40e9cba93c18adf2805da958cba597ba0010ad8e4ed09` | Android 14 原厂 `vendor_boot`（vendor ramdisk 内含 `vr.ko`） |
| `init_boot_patched.img` | 8,388,608 | `e28e22986a3909203389667214df2cf696836324e7f2f6df45f76b36785f2e9c` | KernelSU 3.3.1 补丁（Android 14，KMI android13-5.15） |
| `init_boot_sukisu.img` | 8,388,608 | `d18bd17cec63622a47f5a4c9e6fa1b249aa67ceac46cc026ef4e42b185c1fa72` | SukiSU 4.3.0-r2 补丁（Android 14） |
| `init_boot_a_sukisu.img` | 8,388,608 | `5ec9e0e8a36467a009d57825e97514f34d5ae943f7db4231952db892c6d29896` | Android 15 新槽补丁（**vr 仍在**） |
| `init_boot_a_novr.img` | 8,388,608 | `f603ceef3be72bcb56ebe2a58d2da03081507391ff0fd1fa20088526c28c015f` | Android 15 新槽补丁 + `--block-module vr`（当前使用） |

> 当前设备：Android 15 `PD2227C_A_15.2.11.1.W10`，内核 `5.15.178-gf4fc3f9ca234-dirty`，槽位 `_a`。

## 二、设备侧补丁产物（`/sdcard/Download/`）

| 文件 | 说明 |
|---|---|
| `init_boot_a.img` | 从 `init_boot_a` 分区 dump 出的 Android 15 原厂镜像 |
| `kernelsu_patched_20261108_095448.img` | SukiSU 补丁（A14 init_boot，vr 未屏蔽） |
| `kernelsu_patched_20261108_104548.img` | SukiSU 补丁（A15 init_boot，vr 未屏蔽） |
| `kernelsu_patched_20261108_111652.img` | SukiSU 补丁（A15 init_boot，`--block-module vr`） |

## 三、检测器日志（`com.chunqiunativecheck` v4.6.2）

| 文件 | 说明 |
|---|---|
| `/data/data/com.chunqiunativecheck/files/probe-budgets.tsv` | 123 个探针的耗时预算（明文） |
| `/data/data/com.chunqiunativecheck/files/support-report-queue/*.json` | 7 份报告，ECIES 加密（`key_id`/`client_key`/`iv`/`ciphertext`），本地无法解密 |
| `/sdcard/Android/data/com.chunqiunativecheck/files/error.txt` | 52 KB 明文，23 条 `UNAVAILABLE` 探针及失败原因 |
| `shared_prefs/support_report_upload.xml` | 报告上传状态（`last_queued` / `last_accepted`） |

## 四、本次用到的工具

| 文件 | 说明 |
|---|---|
| [`scripts/vendor_boot_tool.py`](../scripts/vendor_boot_tool.py) | 解析 vendor_boot v3/v4、解压 LZ4 legacy、列出/查找 cpio 内的 `vr.ko` 等文件 |
| [`scripts/patch_inactive_slot.sh`](../scripts/patch_inactive_slot.sh) | 给非当前槽的 `init_boot` 打 SukiSU 补丁（可选 `--block-vr`） |
| [`scripts/extract_payload.py`](../scripts/extract_payload.py) | 从 OTA `payload.bin` 提取 boot/init_boot/vendor_boot |

## 五、为什么不把镜像一起提交

- 仓库定位是**流程与经验记录**，不是固件分发站；README 里也写明"不包含任何厂商固件"；
- vivo 固件受版权约束，公开分发不合适；
- 体积上每个 `init_boot` 8 MB、`vendor_boot` 128 MB，仓库不合适；
- 需要恢复时，用上面的 SHA-256 校验你自己 OTA 提取/本地备份的镜像即可。

> 如需把这些镜像放到你自己的私有存储（网盘/私有仓库），本文的哈希可用于完整性校验。
