---
document_id: nm-basics
title: NetworkManager 基础检查
tags:
  - network
  - networkmanager
  - nmcli
  - openeuler
---
在使用 NetworkManager 管理网络的 openEuler 主机上，排障时先确认设备是否已连接。运行 `nmcli device status` 可以快速查看各网卡设备的连接状态、类型以及当前连接名称。

如果需要查看某个设备获得的 IPv4 地址、默认网关、DNS 等详细信息，可运行 `nmcli device show`，并结合目标设备对应的字段判断配置是否已经生效。

还可以通过 `nmcli connection show --active` 列出当前活动连接。把设备状态、设备详细信息和活动连接放在一起检查，有助于区分“设备未连接”和“连接存在但参数异常”两类问题。
