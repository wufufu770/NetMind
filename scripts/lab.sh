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
  # --cap-add 是必须的：没有 NET_ADMIN 加不了地址、路由，注不了 tc 故障
  for n in r1 r2; do
    ip=$([ "$n" = r1 ] && echo "$R1_SW1" || echo "$R2_SW1")
    docker run -d --name "nm-$n" --hostname "$n" --network "$LAB_SW1" --ip "$ip" \
      --sysctl net.ipv4.ip_forward=1 --cap-add=NET_ADMIN --cap-add=NET_RAW \
      frrouting/frr:latest >/dev/null
  done
  docker network connect --ip "$R1_R2NET" "$LAB_R2NET" nm-r1
  docker network connect --ip "$R2_R2NET" "$LAB_R2NET" nm-r2

  for c in 1 2; do
    docker run -d --name "nm-client$c" --hostname "client$c" --network "$LAB_SW1" \
      --ip "$CLIENT1_IP" --cap-add=NET_ADMIN --cap-add=NET_RAW alpine:3.19 sleep 1d >/dev/null
  done
  docker network disconnect "$LAB_SW1" nm-client2 2>/dev/null || true
  docker network connect --ip 192.168.1.11 "$LAB_SW1" nm-client2
  sleep 1

  # 远端段挂 r2 的跨段口——挂在 r1 自己的口上会让流量不出该段，测不到真路由
  docker exec nm-r2 ip addr add "$FAR_SEG/24" dev eth1
  docker exec nm-r1 ip route add 192.168.3.0/24 via "$R2_R2NET" dev eth1
  docker exec nm-client1 ip route replace 192.168.3.0/24 via "$R1_SW1"

  echo "实验台就绪：client1(${CLIENT1_IP}) → r1(${R1_SW1}) → r2(${R2_R2NET}) → ${FAR_SEG}"
}

# 采一次真实 ping，输出原始报文（供解析，不在此处做判定）
probe() {
  docker exec nm-client1 ping -c "${PING_COUNT:-10}" -i 0.2 -W 2 "$FAR_SEG" 2>&1
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
  echo "── D. FRR 守护进程实况 ──"
  docker exec nm-r2 vtysh -c 'show version' 2>&1 | tail -1 | sed 's/^/  /'
  docker exec nm-r2 sh -c 'pgrep -x zebra >/dev/null && echo "  zebra: running" || echo "  zebra: NOT running（vtysh 拿不到路由表）"'
}

down() {
  for c in nm-client1 nm-client2 nm-r1 nm-r2; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  docker network rm "$LAB_SW1" "$LAB_R2NET" >/dev/null 2>&1 || true
  echo "实验台已清理"
}

case "${1:-up}" in
  up) up ;;
  measure) measure ;;
  down) down ;;
  *) echo "用法: $0 {up|measure|down}"; exit 2 ;;
esac
