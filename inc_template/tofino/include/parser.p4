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
        transition parse_icmp_options;
    }

    state parse_icmp_options {
        packet.extract(hdr.icmp_options);
        transition accept;
    }
    
    state parse_tcp {
        packet.extract(hdr.tcp);

        transition parse_tcp_options;
    }

    state parse_tcp_options {
        packet.extract(hdr.tcp_options,
                       (bit<32>) (hdr.tcp.data_offset - 5) << 5);

        transition accept;
    }

    state parse_udp {
        packet.extract(hdr.udp);
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
            ether_types_t.ARP: parse_inner_arp;
            default: accept;
        }
    }

     state parse_inner_arp {
        packet.extract(hdr.inner_arp);
        transition accept;
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
        meta.l4_meta.src_port = hdr.inner_tcp.src_port;
        meta.l4_meta.dst_port = hdr.inner_tcp.dst_port;

        transition parse_inner_tcp_options;
    }

    state parse_inner_tcp_options {
        packet.extract(hdr.inner_tcp_options,
                       (bit<32>) (hdr.inner_tcp.data_offset - 5) << 5);

        transition accept;
    }

    state parse_inner_udp {
        packet.extract(hdr.inner_udp);
        meta.l4_meta.src_port = hdr.inner_udp.src_port;
        meta.l4_meta.dst_port = hdr.inner_udp.dst_port;
        transition select(hdr.inner_udp.dst_port) {
            8080: parse_udp_application;
            default: accept;
        }
    }

    state parse_udp_application {
        packet.extract(hdr.udp_application);
        transition accept;
    }

    state parse_inner_icmp {
        packet.extract(hdr.inner_icmp);
        transition parse_inner_icmp_options;
    }

    state parse_inner_icmp_options {
        packet.extract(hdr.inner_icmp_options);
        transition accept;
    }

}

/*************************************************************************
************************ D E P A R S E R *********************************
*************************************************************************/
control TenantINCFrameworkIngressDeparser(packet_out packet,
                               inout headers_t hdr, 
                               in metadata_t meta) {
    Checksum() icmp_csum;
        
    apply {
        if (hdr.inner_icmp.isValid()) {
            if (hdr.inner_icmp_options.isValid()) {
                hdr.inner_icmp.checksum = icmp_csum.update({
                    hdr.inner_icmp.type, 
                    hdr.inner_icmp.code,
                    // hdr.inner_icmp.checksum, 
                    hdr.inner_icmp.identifier,
                    hdr.inner_icmp.sequence_number,
                    hdr.inner_icmp.timestamp,
                    hdr.inner_icmp_options.options
                    });
            } else {
                hdr.inner_icmp.checksum = icmp_csum.update({
                    hdr.inner_icmp.type, 
                    hdr.inner_icmp.code,
                    // hdr.inner_icmp.checksum, 
                    hdr.inner_icmp.identifier,
                    hdr.inner_icmp.sequence_number,
                    hdr.inner_icmp.timestamp,
                    (bit<320>) 0
                    });
            }
        }
        
        packet.emit(hdr.ethernet);
        packet.emit(hdr.arp);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.icmp);
        packet.emit(hdr.icmp_options);
        packet.emit(hdr.tcp);
        packet.emit(hdr.tcp_options);
        packet.emit(hdr.udp);
        packet.emit(hdr.vxlan);
        packet.emit(hdr.inner_ethernet);
        packet.emit(hdr.inner_arp);
        packet.emit(hdr.inner_ipv4);
        packet.emit(hdr.inner_icmp);
        packet.emit(hdr.inner_icmp_options);
        packet.emit(hdr.inner_tcp);
        packet.emit(hdr.inner_tcp_options);
        packet.emit(hdr.inner_udp);
        packet.emit(hdr.udp_application);
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
