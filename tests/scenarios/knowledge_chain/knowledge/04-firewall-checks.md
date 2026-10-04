---
document_id: firewall-checks
title: firewalld 连通性检查
tags:
  - firewalld
  - firewall
  - network
  - service
  - openeuler
---
当服务端口已经监听，但客户端仍无法访问时，firewalld 应作为独立检查层，而不是直接把问题归因于服务进程。

先用 `firewall-cmd --get-active-zones` 查看当前活动 zone 以及接口归属，再针对实际 zone 使用 `firewall-cmd --list-services --zone=<zone>` 查看已经允许的 service。

结合监听 socket 和 zone 规则检查，可以区分“服务没有监听”和“服务已监听但防火墙没有按预期放行”这两类问题。本知识文档只描述检查思路与命令，不要求测试逻辑以 root 权限实际修改防火墙。
