"""Shared internal-source policy for Apache live logs and historical snapshots.

Classification uses the effective client address, never the user agent. Public
bots and curl clients remain external traffic. Invalid addresses are retained
for GoAccess to diagnose rather than silently hidden.
"""
import ipaddress

INTERNAL_CIDRS = (
    '0.0.0.0/32', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16',
    '::/128', '::1/128', 'fc00::/7', 'fe80::/10',
)
INTERNAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in INTERNAL_CIDRS)


def is_internal(address):
    """Identify loopback, private, link-local and shared/Tailscale source IPs."""
    try:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return any(ip.version == network.version and ip in network for network in INTERNAL_NETWORKS)
    except ValueError:
        return False


def apache_expression():
    """Render the same policy for Apache's post-remoteip conditional access log."""
    # Apache IPv4 CIDR checks also match IPv4-mapped addresses.
    return ' || '.join("-R '" + network + "'" for network in INTERNAL_CIDRS)


if __name__ == '__main__':
    print(apache_expression())
