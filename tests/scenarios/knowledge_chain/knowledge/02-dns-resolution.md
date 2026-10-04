---
document_id: dns-resolution
title: DNS 解析检查
tags:
  - dns
  - resolver
  - network
  - openeuler
---
在 NetworkManager 环境中，可以先运行 `nmcli device show`，从设备信息中查看当前收到的 DNS 配置，并确认它与正在使用的网络连接相符。

需要验证应用通常经过的系统 resolver 路径时，可运行 `getent hosts <name>`。它通过系统名称服务配置进行解析，因此适合检查“系统能否按正常解析链路获得主机名结果”，而不是绕过系统配置直接向某个 DNS 服务器发查询。

本地排障不把“直接覆盖 resolv.conf”作为首选修复步骤。应先确认 NetworkManager 下发的配置、活动连接和系统 resolver 的实际行为，再决定是否需要调整持久化网络配置。
