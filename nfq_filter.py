
# ~/nfq_filter.py
from netfilterqueue import NetfilterQueue
from scapy.all import IP, UDP, TCP, raw

PORT = 24680

def handle(pkt):
    ip = IP(pkt.get_payload())

    # UDP example: replace a string in payload
    if UDP in ip and (ip[UDP].dport == PORT or ip[UDP].sport == PORT):
        pld = bytes(ip[UDP].payload)
        new_pld = pld.replace(b"OLD", b"NEW")
        if new_pld != pld:
            ip[UDP].remove_payload()
            ip[UDP].add_payload(new_pld)
            # let Scapy recalc lengths/checksums
            del ip.len, ip.chksum, ip[UDP].len, ip[UDP].chksum
            pkt.set_payload(raw(ip))

    # For TCP, you can modify payload too, but be mindful of sequence/segmentation.
    pkt.accept()

if __name__ == "__main__":
    nfq = NetfilterQueue()
    nfq.bind(0, handle)
    try:
        nfq.run()
    finally:
        nfq.unbind()
