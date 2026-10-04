---
document_id: service-diagnostics
title: systemd 服务诊断
tags:
  - systemd
  - service
  - journal
  - socket
  - openeuler
---
诊断 systemd 服务时，可以先使用 `systemctl status <service>` 查看服务当前状态和最近的状态摘要，再使用 `journalctl -u <service>` 查看该服务对应的日志，定位启动失败、配置错误或运行期异常。

服务显示为 active 并不代表客户端所需端口一定已经监听。可以继续运行 `ss -lntp` 查看 TCP 监听 socket，并核对监听地址、端口以及关联进程。

因此，服务状态正常不等于端口一定已经监听。状态、日志和 socket 是彼此独立但相互补充的检查层。
