#!/bin/bash

# U-OPTI - System Information Module
# v0.8.0

show_system_information() {
    clear

    echo "======================================"
    echo "         System Information"
    echo "======================================"
    echo

    OS_NAME=$(. /etc/os-release && echo "$PRETTY_NAME")
    KERNEL=$(uname -r)
    ARCH=$(uname -m)
    CPU_CORES=$(nproc)

    RAM_TOTAL=$(free -h | awk '/^Mem:/ {print $2}')
    RAM_USED=$(free -h | awk '/^Mem:/ {print $3}')
    RAM_FREE=$(free -h | awk '/^Mem:/ {print $7}')

    DISK_INFO=$(df -h / | awk 'NR==2 {
        printf "%s total, %s used, %s free", $2, $3, $4
    }')

    UPTIME=$(uptime -p)
    TIMEZONE=$(timedatectl show --property=Timezone --value)
    NTP_SYNC=$(timedatectl show --property=NTPSynchronized --value)

    if [ "$NTP_SYNC" = "yes" ]; then
        NTP_STATUS="Synchronized"
    else
        NTP_STATUS="Not Synchronized"
    fi

    SWAP_TOTAL=$(free -h | awk '/^Swap:/ {print $2}')
    SWAP_USED=$(free -h | awk '/^Swap:/ {print $3}')

    if swapon --show | grep -q .; then
        SWAP_STATUS="Enabled ($SWAP_TOTAL)"
    else
        SWAP_STATUS="Disabled"
    fi

    CURRENT_CC=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "Unknown")
    AVAILABLE_CC=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || echo "Unknown")
    DEFAULT_QDISC=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "Unknown")

    if echo "$AVAILABLE_CC" | grep -qw "bbr"; then
        if [ "$CURRENT_CC" = "bbr" ]; then
            BBR_STATUS="Enabled"
        else
            BBR_STATUS="Available / Disabled"
        fi
    else
        BBR_STATUS="Not Available"
    fi

    IPV4=$(hostname -I | awk '{print $1}')

    if ip -6 addr show scope global | grep -q inet6; then
        IPV6_STATUS="Enabled"
    else
        IPV6_STATUS="Disabled"
    fi

    echo "OS           : $OS_NAME"
    echo "Kernel       : $KERNEL"
    echo "Architecture : $ARCH"
    echo "CPU Cores    : $CPU_CORES"
    echo "RAM          : $RAM_USED / $RAM_TOTAL used"
    echo "RAM Free     : $RAM_FREE"
    echo "Disk         : $DISK_INFO"
    echo "Uptime       : $UPTIME"
    echo
    echo "Timezone     : $TIMEZONE"
    echo "NTP          : $NTP_STATUS"
    echo
    echo "Swap         : $SWAP_STATUS"
    echo "Swap Used    : $SWAP_USED"
    echo
    echo "IPv4         : ${IPV4:-Not Available}"
    echo "IPv6         : $IPV6_STATUS"
    echo
    echo "BBR          : $BBR_STATUS"
    echo "Congestion   : $CURRENT_CC"
    echo "Default Qdisc: $DEFAULT_QDISC"

    echo
    echo "Available Congestion Controls:"
    echo "$AVAILABLE_CC"

    echo
    echo "--------------------------------------"
    echo
    read -rp "Press Enter to return..."
}
