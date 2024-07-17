/*************************************************************************
************************** P A R S E R ***********************************
*************************************************************************/

#ifndef __PARSER__
#define __PARSER__

parser TenantINCFrameworkIngressParser(packet_in packet,
                            out headers_t hdr,
                            out metadata_t meta,
                            out ingress_intrinsic_metadata_t ig_intr_md) {

    state start {
        packet.extract(ig_intr_md);
        packet.advance(PORT_METADATA_SIZE);
        meta.l4_meta.src_port = 0;
        meta.l4_meta.dst_port = 0;
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);

        transition select(hdr.ethernet.ether_type) {
            ether_types_t.IPV4: parse_ipv4;
            ether_types_t.ARP: parse_arp;
            default: accept;    // reject;
        }
    }

    state parse_arp {
        packet.extract(hdr.arp);
        transition accept;
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);

        // TODO: verify is currently unsupported!
        // verify(hdr.ipv4.version == 4w4, error.IPv4IncorrectVersion);
        // verify(hdr.ipv4.ihl >= 4w5, error.IPv4HeaderTooShort);
        // verify(hdr.ipv4.ihl == 4w5, error.IPv4OptionsNotSupported);

        transition select(hdr.ipv4.ihl) {
            0x5: parse_ipv4_no_options;
            0x6 &&& 0xE: parse_ipv4_options;
            0x8 &&& 0x8: parse_ipv4_options;
            _ : accept;    // reject;
        }
    }

    state parse_ipv4_options {
        packet.extract(hdr.ipv4_options,
                       ( (bit<32>) hdr.ipv4.ihl - 5) * 32);
        transition parse_ipv4_no_options;
    }

    state parse_ipv4_no_options {
        meta.ingress_meta.l4_lookup = packet.lookahead<l4_lookup_t>();

        transition select(hdr.ipv4.protocol) {
            ip_protos_t.ICMP: parse_icmp;
            ip_protos_t.TCP: parse_tcp;
            ip_protos_t.UDP: parse_udp;
            default: accept;    // reject;
        }
    }

    state parse_icmp {
        packet.extract(hdr.icmp);
        transition accept;
    }
    
    state parse_tcp {
        packet.extract(hdr.tcp);
        meta.l4_meta.src_port = hdr.tcp.src_port;
        meta.l4_meta.dst_port = hdr.tcp.dst_port;
        transition parse_tcp_options;
    }

    state parse_tcp_options {
        packet.extract(hdr.tcp_options,
                       (bit<32>) (hdr.tcp.data_offset - 5) << 5);

        transition accept;
    }

    state parse_udp {
        packet.extract(hdr.udp);
        meta.l4_meta.src_port = hdr.udp.src_port;
        meta.l4_meta.dst_port = hdr.udp.dst_port;
        // Check for parsing VXLAN
        transition select(hdr.udp.dst_port) {
            UDP_PORT_VXLAN: parse_vxlan;

            default: accept;
         }
        
    }

    state parse_vxlan {
        packet.extract(hdr.vxlan);
        meta.tenant_meta.tenant_id = hdr.vxlan.vni;
        meta.tenant_meta.export_flag = 0;
        transition parse_inner_ethernet;
        // transition accept;
    }

    state parse_inner_ethernet {
        packet.extract(hdr.inner_ethernet);
        transition select(hdr.inner_ethernet.ether_type) {
            ether_types_t.IPV4: parse_inner_ipv4;
            default: accept;
        }
    }

    state parse_inner_ipv4 {
        packet.extract(hdr.inner_ipv4);
        transition parse_inner_ipv4_options;
    }

    state parse_inner_ipv4_options {
        packet.extract(hdr.inner_ipv4_options,
                       ((bit<32>)hdr.inner_ipv4.ihl - 5) * 32);

        transition parse_inner_ipv4_no_options;
    }

    state parse_inner_ipv4_no_options {
        meta.ingress_meta.inner_l4_lookup = packet.lookahead<l4_lookup_t>();

        transition select(hdr.inner_ipv4.protocol) {
            ip_protos_t.ICMP: parse_inner_icmp;
            ip_protos_t.TCP: parse_inner_tcp;
            ip_protos_t.UDP: parse_inner_udp;
            default: accept;    // reject;
        }
    }

    state parse_inner_tcp {
        packet.extract(hdr.inner_tcp);

        transition parse_inner_tcp_options;
    }

    state parse_inner_tcp_options {
        packet.extract(hdr.inner_tcp_options,
                       (bit<32>) (hdr.inner_tcp.data_offset - 5) << 5);

        transition accept;
    }

    state parse_inner_udp {
        packet.extract(hdr.inner_udp);

        transition accept;
    }

    state parse_inner_icmp {
        packet.extract(hdr.inner_icmp);
        transition accept;
    }
}

/*************************************************************************
************************ D E P A R S E R *********************************
*************************************************************************/
control TenantINCFrameworkIngressDeparser(packet_out packet,
                               inout headers_t hdr, 
                               in metadata_t meta) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.arp);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.icmp);
        packet.emit(hdr.tcp);
        packet.emit(hdr.tcp_options);
        packet.emit(hdr.udp);
        packet.emit(hdr.vxlan);
        packet.emit(hdr.inner_ethernet);
        packet.emit(hdr.inner_ipv4);
        packet.emit(hdr.inner_icmp);
        packet.emit(hdr.inner_tcp);
        packet.emit(hdr.inner_tcp_options);
        packet.emit(hdr.inner_udp);
    }
}

parser TenantINCFrameworkEgressParser(packet_in pkt,
                      out headers_t hdr,
                      out metadata_t meta,
                      out egress_intrinsic_metadata_t eg_intr_md) {
    state start {
        pkt.extract(eg_intr_md);
        transition accept;
    }
}


// nothing changed, so no need to deparse (i.e., serialize) modified packet data like header fields
control TenantINCFrameworkEgressDeparser(packet_out pkt,
                       inout headers_t hdr,
                       in metadata_t meta,
                       in egress_intrinsic_metadata_for_deparser_t eg_dprsr_md) { apply { pkt.emit(hdr); } }



#endif  // __PARSER__
