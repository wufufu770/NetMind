#!/usr/bin/env bash
# 真实网络实验台：起一组真的容器、真的路由、真的 ICMP，供 diagnose 采真数据。
#
# 拓扑（与 examples/clab-demo.yml 同构，但用 docker 原生网络实现，依赖更少）：
#
#   client1 ──┐                      ┌── client2
#             ├─ nm-sw1 (192.168.1/24) ─┤
#        r1 ──┘        │                 └── r2
#                      └─ nm-r2net (192.168.2/24) ─┐
#                                                   └─ 192.168.3.0/24 (挂在 r2)
#
# 探测路径 client1 → 192.168.3.1 是真两跳 L3：client1 → r1 → r2 → 远端段。
# 不经过它就拿不到真实延迟/丢包，遥测就只能靠硬编码常量。
#
# 用法：
#   scripts/lab.sh up       起实验台并完成布线
#   scripts/lab.sh measure  采一组真实遥测（三态：健康/拥塞/断链）
#   scripts/lab.sh down     清理
set -euo pipefail

LAB_SW1=nm-sw1
LAB_R2NET=nm-r2net
CLIENT1_IP=192.168.1.10
CLIENT2_IP=192.168.1.11
R1_SW1=192.168.1.2
R2_SW1=192.168.1.3
R1_R2NET=192.168.2.2
R2_R2NET=192.168.2.3
FAR_SEG=192.168.3.1

up() {
  down 2>/dev/null || true
  docker network create --driver bridge --subnet 192.168.1.0/24 --gateway 192.168.1.1 "$LAB_SW1" >/dev/null
  docker network create --driver bridge --subnet 192.168.2.0/24 --gateway 192.168.2.1 "$LAB_R2NET" >/dev/null

  # --sysctl 必须在启动时注入：FRR 镜像的 /proc/sys 是只读的，运行期改不了
  # --cap-add NET_ADMIN/RAW：加地址路由、注 tc 故障需要
  # --cap-add SYS_ADMIN：zebra 启动时做 cap_set_proc 必须要它。缺了会静默失败——
  #   watchfrr 照常起 staticd，但 zebra 进程不出现，/var/run/frr 下只有 staticd.vty
  #   没有 zebra.vty，vtysh 报 "zebra is not running" 却查不出真正原因。
  for n in r1 r2; do
    ip=$([ "$n" = r1 ] && echo "$R1_SW1" || echo "$R2_SW1")
    docker run -d --name "nm-$n" --hostname "$n" --network "$LAB_SW1" --ip "$ip" \
      --sysctl net.ipv4.ip_forward=1 \
      --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SYS_ADMIN \
      frrouting/frr:latest >/dev/null
  done
  docker network connect --ip "$R1_R2NET" "$LAB_R2NET" nm-r1
  docker network connect --ip "$R2_R2NET" "$LAB_R2NET" nm-r2

  # client1 / client2 的地址不同，循环里必须按序号取，不能两个都给 CLIENT1_IP
  # 客户端：client2 额外装了 iproute2——自愈闭环要在这台设备上真下发
  # tc qdisc del，而 alpine 基础镜像不带 iproute2（tc 在单独的包里）。
  # 没有它，自愈只能生成命令下发到没 tc 的设备上，验证不了「真改变了什么」。
  for c in 1 2; do
    cip=$([ "$c" = 1 ] && echo "$CLIENT1_IP" || echo "$CLIENT2_IP")
    docker run -d --name "nm-client$c" --hostname "client$c" --network "$LAB_SW1" \
      --ip "$cip" --cap-add=NET_ADMIN --cap-add=NET_RAW \
      -e PASSWORD=netmind123 -e PASSWORD_ACCESS=true \
      -e USER_NAME=netmind -e USER_PASSWORD=netmind123 -e USER_PASSWORD_ACCESS=true \
      -e SUDO_ACCESS=true linuxserver/openssh-server >/dev/null
  done
  # 等 sshd 就绪后给 client2 装 tc
  sleep 8
  docker exec nm-client2 sh -c 'apk add --no-cache iproute2 >/dev/null 2>&1 || true'
  # 监控账号用 NOPASSWD sudo 提权。生产里也应如此：让工具去提示输密码既不可用
  # 也不安全。NetMind 的 NETMIND_SUDO 依赖这个前提。
  docker exec nm-client2 sh -c "echo 'netmind ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/netmind && chmod 440 /etc/sudoers.d/netmind" 2>/dev/null || true
  sleep 4   # 等 FRR 的 watchfrr 把 zebra 拉起来

  # 被监控主机：真实 SSH 端点，主链路的探测从这里发起。
  # 必须给 NET_ADMIN——没有它连容器内 root 都加不了路由，主链路就测不了跨段路径。
  docker rm -f nm-dev1 >/dev/null 2>&1 || true
  docker run -d --name nm-dev1 --hostname dev1 --network "$LAB_SW1" --ip 192.168.1.30 \
    --cap-add=NET_ADMIN --cap-add=NET_RAW \
    -e PASSWORD=netmind123 -e PASSWORD_ACCESS=true \
    -e USER_NAME=netmind -e USER_PASSWORD=netmind123 -e USER_PASSWORD_ACCESS=true \
    -e SUDO_ACCESS=true linuxserver/openssh-server >/dev/null
  sleep 8   # 等 sshd 就绪

  # 远端段挂 r2 的跨段口——挂在 r1 自己的口上会让流量不出该段，测不到真路由
  docker exec nm-r2 ip addr add "$FAR_SEG/24" dev eth1
  docker exec nm-r1 ip route replace 192.168.3.0/24 via "$R2_R2NET" dev eth1
  docker exec nm-client1 ip route replace 192.168.3.0/24 via "$R1_SW1"
  # 被监控主机也要一条经 r1 到远端段的路由，否则探测只走同段，测不到跨段劣化
  docker exec nm-dev1 ip route replace 192.168.3.0/24 via "$R1_SW1"

  echo "实验台就绪：client1(${CLIENT1_IP}) → r1(${R1_SW1}) → r2(${R2_R2NET}) → ${FAR_SEG}"
  echo "  被监控主机 dev1 = 192.168.1.30:2222（netmind/netmind123），主链路从这里探测"
  echo "  可处置主机 client2 = ${CLIENT2_IP}:2222（netmind/netmind123），带 tc，自愈闭环在这里跑"
}

# 采一次真实 ping，输出原始报文（供解析，不在此处做判定）
# ping 在 100% 丢包时退出码非 0。脚本头是 set -euo pipefail，直接跑会在
# 「全断」这个最该测出来的场景上当场退出——测不到自己要测的东西。
# 这里吞掉退出码但保留全部输出；判定交给调用方看报文，不看退出码。
probe() {
  docker exec nm-client1 ping -c "${PING_COUNT:-10}" -i 0.2 -W 2 "$FAR_SEG" 2>&1 || true
}

measure() {
  echo "── A. 健康基线 ──"
  probe | grep -E 'packet loss|round-trip' | sed 's/^/  /'
  echo "── B. 真实拥塞（r1 出口 netem delay 120ms loss 8%）──"
  docker exec nm-r1 tc qdisc add dev eth1 root netem delay 120ms loss 8% >/dev/null 2>&1 || true
  probe | grep -E 'packet loss|round-trip' | sed 's/^/  /'
  docker exec nm-r1 tc qdisc del dev eth1 root >/dev/null 2>&1 || true
  echo "── C. 真实断链（down r2 跨段口）──"
  docker exec nm-r2 ip link set eth1 down
  probe | grep -E 'packet loss|round-trip' | sed 's/^/  /'
  docker exec nm-r2 ip link set eth1 up
  echo "── D. FRR 守护进程与真实路由表 ──"
  docker exec nm-r2 vtysh -c 'show version' 2>&1 | tail -1 | sed 's/^/  /'
  docker exec nm-r2 sh -c 'ls /var/run/frr/zebra.vty >/dev/null 2>&1 && echo "  zebra: running" || echo "  zebra: NOT running（检查是否缺 --cap-add=SYS_ADMIN）"'
  docker exec nm-r2 vtysh -c 'show ip route' 2>/dev/null | grep -E '^[KCSOR]>?' | sed 's/^/    /'
}

down() {
  for c in nm-client1 nm-client2 nm-r1 nm-r2 nm-dev1; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  docker network rm "$LAB_SW1" "$LAB_R2NET" >/dev/null 2>&1 || true
  echo "实验台已清理"
}

case "${1:-up}" in
  up) up ;;
  measure) measure ;;
  down) down ;;
  *) echo "用法: $0 {up|measure|down}"; exit 2 ;;
esac
