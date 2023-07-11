/*************************************************************************
************************** P A R S E R ***********************************
*************************************************************************/

#ifndef __PARSER__
#define __PARSER__

parser TenantRFClassificationParser(packet_in packet,
                            out headers_t hdr,
                            inout metadata_t meta,
                            inout standard_metadata_t standard_metadata) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);

        transition select(hdr.ethernet.ether_type) {
            ether_types_t.IPV4: parse_ipv4;
            ether_types_t.FLOW_MONITORING:  parse_flow_monitoring;
            ether_types_t.FLOW_EXPORT_REQUEST: parse_flow_export_request;
            ether_types_t.FLOW_EXPORT_RESPONSE: parse_flow_export_response;
            default: accept;    // reject;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);

        verify(hdr.ipv4.version == 4w4, error.IPv4IncorrectVersion);
        verify(hdr.ipv4.ihl >= 4w5, error.IPv4HeaderTooShort);
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
                       ((bit<32>)hdr.ipv4.ihl - 32w5) * 32);

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

// #if USE_PM
//         transition parse_pm;
// #else
        transition accept;
// #endif
    }
    
    state parse_tcp {
        packet.extract(hdr.tcp);

        transition parse_tcp_options;
    }

    state parse_tcp_options {
        packet.extract(hdr.tcp_options,
                       (bit<32>) (hdr.tcp.data_offset - 5) << 5);
#if USE_PM
        transition accept;
#else
        transition parse_pm;
#endif 
    }

    state parse_udp {
        packet.extract(hdr.udp);
        // Check for parsing VXLAN
        transition select(hdr.udp.dst_port) {
            UDP_PORT_VXLAN: parse_vxlan;
#if USE_PM
            default: parse_pm;
#else
            default: accept;
#endif
         }
        
    }

    state parse_vxlan {
        packet.extract(hdr.vxlan);
        meta.tenant_meta.tenant_id = hdr.vxlan.vni;
        meta.tenant_meta.export_flag = 0;
        transition parse_inner_ethernet;
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
        packet.extract(hdr.ipv4_options,
                       ((bit<32>)hdr.ipv4.ihl - 32w5) * 32);

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
        // log_msg("Parse TCP: ");
        meta.l4_meta.src_port = hdr.inner_tcp.src_port;
        meta.l4_meta.dst_port = hdr.inner_tcp.dst_port;

        transition parse_inner_tcp_options;
        // transition parse_pm;
    }

    state parse_inner_tcp_options {
        packet.extract(hdr.inner_tcp_options,
                       (bit<32>) (hdr.inner_tcp.data_offset - 5) << 5);

#if USE_PM
        transition parse_pm;
#else
        transition accept;
#endif
    }

    state parse_inner_udp {
        packet.extract(hdr.inner_udp);
        // log_msg("Parse UDP: ");
        meta.l4_meta.src_port = hdr.inner_udp.src_port;
        meta.l4_meta.dst_port = hdr.inner_udp.dst_port;

#if USE_PM
        transition parse_pm;
#else
        transition accept;
#endif
    }

    state parse_inner_icmp {
        packet.extract(hdr.inner_icmp);

    // #if USE_PM
    //         transition parse_pm;
    // #else
            transition accept;
    // #endif
        }

    state parse_pm {
        packet.extract(hdr.pm);
        // log_msg("Parse PM: ");

        transition accept;
    }

    state parse_flow_monitoring {
        packet.extract(hdr.flow_mon);

        transition accept;
    }

    state parse_flow_export_request {
        packet.extract(hdr.flow_export_request);

        transition accept;
    }

    state parse_flow_export_response {
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
        packet.extract(hdr.flow_record_data);
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
        packet.extract(hdr.biflow_record_data);
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

        transition accept;
    }
}

/*************************************************************************
************************ D E P A R S E R *********************************
*************************************************************************/
control TenantRFClassificationDeparser(packet_out packet,
                               in headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);
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
        packet.emit(hdr.pm);
        packet.emit(hdr.flow_mon);
        packet.emit(hdr.tenant);
        packet.emit(hdr.flow_export_request);
        packet.emit(hdr.flow_export_response);
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
        packet.emit(hdr.flow_record_data);
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
        packet.emit(hdr.biflow_record_data);
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
        packet.emit(hdr.analyzer);
    }
}

#endif  // __PARSER__
