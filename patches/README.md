# bootstrap.c 改动（DirtyFrag-vr 1.16）

`bootstrap.c` 负责在 dfroot.ko 的 root 上下文里启动 KernelSU 的
`ksud late-load`。原版在 vivo 内核上会静默失败，因为 KSU 无法从内核版本串
识别 KMI。

## 必要改动

给 late-load 显式传入 KMI：

```c
static const char KSU_KMI[] = "android13-5.15"; /* 5.15 机型按实际 KMI 修改 */

int lrc = run_ctx(NULL, (char *[]){
    KSUD_STAGE, "late-load",
    "--package-name", su_manager,
    "--kmi", KSU_KMI,
    NULL
});
```

## 可选：把失败原因落盘

`ksud late-load` 会 daemonize，父进程立即返回 0，真正的错误在 daemon 里；
把 stdout/stderr 重定向到文件即可看到（daemon 会自行关闭 stdio，若看不到，
可改用 logcat 或 `ksud late-load` 前不要 daemonize 的调试构建）：

```c
int lfd = open("/data/local/tmp/ksu_late.log",
               O_CREAT | O_WRONLY | O_TRUNC, 0666);
if (lfd >= 0) { dup2(lfd, 1); dup2(lfd, 2); close(lfd); }
```

## 临时 root 用到的其它调试代码（可删）

```c
/* 导出内核 dmesg，确认 dfroot.ko 的 init 走到了哪一步 */
system("dmesg > /data/local/tmp/dmesg_after.txt 2>&1");
/* 解锁用：把补丁后的 devinfo 写回分区 */
system("dd if=/data/local/tmp/devinfo_patched.img "
       "of=/dev/block/by-name/devinfo bs=4096 count=1");
```
