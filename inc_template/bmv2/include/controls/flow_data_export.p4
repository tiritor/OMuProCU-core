control FlowDataExport(inout headers_t hdr,
                       inout metadata_t meta,
                       inout standard_metadata_t standard_metadata) {
    
    // action anonymize_ip_address_action(inout ipv4_address_t ip_address) {
    //     ipv4_address_t ip_address_anonymization_mask;
    //     ip_address_anonymization_mask_register.read(ip_address_anonymization_mask, 0);
    //     ip_address = (ip_address | ip_address_anonymization_mask);
    // }

    // flow export response
    action build_flow_export_response_action() {
        hdr.ethernet.ether_type = ether_types_t.FLOW_EXPORT_RESPONSE;
        hdr.ethernet.src_addr = FLOW_EXPORT_REQUEST_PACKET_DST_MAC;
        hdr.ethernet.dst_addr = FLOW_EXPORT_REQUEST_PACKET_SRC_MAC;

        hdr.flow_export_response.setValid();
        // hdr.flow_export_response.flow_type = flow_type;
        hdr.flow_export_response.flow_type = meta.flow_type;
        hdr.flow_export_response.flow_hash = meta.flow_hash;
    }

    action build_tenant_action(){
        hdr.tenant.setValid();
        hdr.tenant.tenant_id = hdr.vxlan.vni;
        hdr.tenant.tenant_func_id = meta.tenant_meta.tenant_func_id;
    }

    action build_analyzer_export_action() {
        hdr.analyzer.setValid();
        hdr.analyzer.class = meta.feature_meta.class;
        hdr.analyzer.probability = (bit<64>) meta.feature_meta.probability;
        hdr.analyzer.malware = (bit<16>) meta.feature_meta.malware;
        hdr.analyzer.tree_count = meta.feature_meta.tree_count;
    }

#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
    // flow record
    action build_flow_record_action() {
        hdr.flow_record_data.setValid();

        hdr.flow_record_data.reserved = 0;

        // flow export condition
        hdr.flow_record_data.export_condition = meta.flow_export_reason;

        // flow 5-tuple
        flow_src_ip_register.read(hdr.flow_record_data.src_ip, meta.flow_hash);
        // anonymize_ip_address_action(hdr.flow_record_data.src_ip);
        flow_dst_ip_register.read(hdr.flow_record_data.dst_ip, meta.flow_hash);
        // anonymize_ip_address_action(hdr.flow_record_data.dst_ip);
        flow_ip_protocol_register.read(hdr.flow_record_data.ip_protocol, meta.flow_hash);
        flow_src_port_register.read(hdr.flow_record_data.src_port, meta.flow_hash);
        flow_dst_port_register.read(hdr.flow_record_data.dst_port, meta.flow_hash);

        // flow first/last seen timestamp
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> timestamp_tmp;
        flow_first_packet_timestamp_register.read(timestamp_tmp, meta.flow_hash);
        hdr.flow_record_data.start = (bit<64>) timestamp_tmp;
        flow_last_packet_timestamp_register.read(timestamp_tmp, meta.flow_hash);
        hdr.flow_record_data.end = (bit<64>) timestamp_tmp;

        // flow packets and bytes counter
        bidirectional_packet_register.read(hdr.flow_record_data.packets, meta.flow_hash);
        bidirectional_byte_register.read(hdr.flow_record_data.bytes, meta.flow_hash);

        // flow packet length (min, max, moving average)
        flow_packet_length_min_register.read(hdr.flow_record_data.packet_length_min, meta.flow_hash);
        flow_packet_length_max_register.read(hdr.flow_record_data.packet_length_max, meta.flow_hash);
        flow_packet_length_mean_register.read(hdr.flow_record_data.packet_length_mean, meta.flow_hash);

        // flow packet inter-arrival time (min, max, moving average)
        flow_packet_inter_arrival_time_min_register.read(timestamp_tmp, meta.flow_hash);
        hdr.flow_record_data.packet_inter_arrival_time_min = (bit<64>) timestamp_tmp;
        flow_packet_inter_arrival_time_max_register.read(timestamp_tmp, meta.flow_hash);
        hdr.flow_record_data.packet_inter_arrival_time_max = (bit<64>) timestamp_tmp;
        flow_packet_inter_arrival_time_mean_register.read(timestamp_tmp, meta.flow_hash);
        hdr.flow_record_data.packet_inter_arrival_time_mean = (bit<64>) timestamp_tmp;

        // flow TCP flags
        // flow_tcp_flags_mask_register.read(hdr.flow_record_data.tcp_flags, meta.flow_hash);
        // // flow TCP flags counts
        // flow_tcp_flags_FIN_count_register.read(hdr.flow_record_data.tcp_flags_FIN_count, meta.flow_hash);
        // flow_tcp_flags_SYN_count_register.read(hdr.flow_record_data.tcp_flags_SYN_count, meta.flow_hash);
        // flow_tcp_flags_RST_count_register.read(hdr.flow_record_data.tcp_flags_RST_count, meta.flow_hash);
        // flow_tcp_flags_PSH_count_register.read(hdr.flow_record_data.tcp_flags_PSH_count, meta.flow_hash);
        // flow_tcp_flags_ACK_count_register.read(hdr.flow_record_data.tcp_flags_ACK_count, meta.flow_hash);
        // flow_tcp_flags_URG_count_register.read(hdr.flow_record_data.tcp_flags_URG_count, meta.flow_hash);
        // flow_tcp_flags_ECE_count_register.read(hdr.flow_record_data.tcp_flags_ECE_count, meta.flow_hash);
        // flow_tcp_flags_CWR_count_register.read(hdr.flow_record_data.tcp_flags_CWR_count, meta.flow_hash);
    }
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))

#if  (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    // biflow record
    action build_biflow_record_action() {
        hdr.biflow_record_data.setValid();

        hdr.biflow_record_data.reserved = 0;

        // flow export condition
        hdr.biflow_record_data.export_condition = meta.flow_export_reason;

        // flow 5-tuple
        flow_src_ip_register.read(hdr.biflow_record_data.src_ip, meta.flow_hash);
        // anonymize_ip_address_action(hdr.biflow_record_data.src_ip);
        flow_dst_ip_register.read(hdr.biflow_record_data.dst_ip, meta.flow_hash);
        // anonymize_ip_address_action(hdr.biflow_record_data.dst_ip);
        flow_ip_protocol_register.read(hdr.biflow_record_data.ip_protocol, meta.flow_hash);
        flow_src_port_register.read(hdr.biflow_record_data.src_port, meta.flow_hash);
        flow_dst_port_register.read(hdr.biflow_record_data.dst_port, meta.flow_hash);

        // biflow forward start and end timestamps
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> timestamp_tmp;
        flow_forward_first_seen_timestamp_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.forward_start = (bit<64>) timestamp_tmp;
        flow_forward_last_seen_timestamp_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.forward_end = (bit<64>) timestamp_tmp;

        // biflow forward packets and bytes counter
        flow_forward_packets_counter.read(hdr.biflow_record_data.forward_packets, meta.flow_hash);
        flow_forward_bytes_counter.read(hdr.biflow_record_data.forward_bytes, meta.flow_hash);

        // biflow forward TCP flags
        // flow_forward_tcp_flags_mask_register.read(hdr.biflow_record_data.forward_tcp_flags, meta.flow_hash);
        // // biflow forward TCP flags counts
        // flow_forward_tcp_flags_FIN_count_register.read(hdr.biflow_record_data.forward_tcp_flags_FIN_count, meta.flow_hash);
        // flow_forward_tcp_flags_SYN_count_register.read(hdr.biflow_record_data.forward_tcp_flags_SYN_count, meta.flow_hash);
        // flow_forward_tcp_flags_RST_count_register.read(hdr.biflow_record_data.forward_tcp_flags_RST_count, meta.flow_hash);
        // flow_forward_tcp_flags_PSH_count_register.read(hdr.biflow_record_data.forward_tcp_flags_PSH_count, meta.flow_hash);
        // flow_forward_tcp_flags_ACK_count_register.read(hdr.biflow_record_data.forward_tcp_flags_ACK_count, meta.flow_hash);
        // flow_forward_tcp_flags_URG_count_register.read(hdr.biflow_record_data.forward_tcp_flags_URG_count, meta.flow_hash);
        // flow_forward_tcp_flags_ECE_count_register.read(hdr.biflow_record_data.forward_tcp_flags_ECE_count, meta.flow_hash);
        // flow_forward_tcp_flags_CWR_count_register.read(hdr.biflow_record_data.forward_tcp_flags_CWR_count, meta.flow_hash);

        // biflow forward packet length
        flow_forward_packet_length_min_register.read(hdr.biflow_record_data.forward_packet_length_min, meta.flow_hash);
        flow_forward_packet_length_max_register.read(hdr.biflow_record_data.forward_packet_length_max, meta.flow_hash);
        flow_forward_packet_length_mean_register.read(hdr.biflow_record_data.forward_packet_length_mean, meta.flow_hash);

        // biflow forward packet inter-arrival time
        flow_forward_packet_inter_arrival_time_min_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.forward_packet_inter_arrival_time_min = (bit<64>) timestamp_tmp;
        flow_forward_packet_inter_arrival_time_max_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.forward_packet_inter_arrival_time_max = (bit<64>) timestamp_tmp;
        flow_forward_packet_inter_arrival_time_mean_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.forward_packet_inter_arrival_time_mean = (bit<64>) timestamp_tmp;

        // biflow backward start and end timestamps        
        flow_backward_first_seen_timestamp_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.backward_start = (bit<64>) timestamp_tmp;
        flow_backward_last_seen_timestamp_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.backward_end = (bit<64>) timestamp_tmp;

        // biflow backward packets and bytes counter
        flow_backward_packets_counter.read(hdr.biflow_record_data.backward_packets, meta.flow_hash);
        flow_backward_bytes_counter.read(hdr.biflow_record_data.backward_bytes, meta.flow_hash);

        // biflow backward TCP flags
        // flow_backward_tcp_flags_mask_register.read(hdr.biflow_record_data.backward_tcp_flags, meta.flow_hash);
        // // biflow backward TCP flags counts        
        // flow_backward_tcp_flags_FIN_count_register.read(hdr.biflow_record_data.backward_tcp_flags_FIN_count, meta.flow_hash);
        // flow_backward_tcp_flags_SYN_count_register.read(hdr.biflow_record_data.backward_tcp_flags_SYN_count, meta.flow_hash);
        // flow_backward_tcp_flags_RST_count_register.read(hdr.biflow_record_data.backward_tcp_flags_RST_count, meta.flow_hash);
        // flow_backward_tcp_flags_PSH_count_register.read(hdr.biflow_record_data.backward_tcp_flags_PSH_count, meta.flow_hash);
        // flow_backward_tcp_flags_ACK_count_register.read(hdr.biflow_record_data.backward_tcp_flags_ACK_count, meta.flow_hash);
        // flow_backward_tcp_flags_URG_count_register.read(hdr.biflow_record_data.backward_tcp_flags_URG_count, meta.flow_hash);
        // flow_backward_tcp_flags_ECE_count_register.read(hdr.biflow_record_data.backward_tcp_flags_ECE_count, meta.flow_hash);
        // flow_backward_tcp_flags_CWR_count_register.read(hdr.biflow_record_data.backward_tcp_flags_CWR_count, meta.flow_hash);

        // biflow backward packet length
        flow_backward_packet_length_min_register.read(hdr.biflow_record_data.backward_packet_length_min, meta.flow_hash);
        flow_backward_packet_length_max_register.read(hdr.biflow_record_data.backward_packet_length_max, meta.flow_hash);
        flow_backward_packet_length_mean_register.read(hdr.biflow_record_data.backward_packet_length_mean, meta.flow_hash);

        // biflow backward packet inter-arrival time
        flow_backward_packet_inter_arrival_time_min_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.backward_packet_inter_arrival_time_min = (bit<64>) timestamp_tmp;
        flow_backward_packet_inter_arrival_time_max_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.backward_packet_inter_arrival_time_max = (bit<64>) timestamp_tmp;
        flow_backward_packet_inter_arrival_time_mean_register.read(timestamp_tmp, meta.flow_hash);
        hdr.biflow_record_data.backward_packet_inter_arrival_time_mean = (bit<64>) timestamp_tmp;
    }
    
#endif // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

    action send_to_port_action(port_id_t egress_port) {
        standard_metadata.egress_spec = egress_port;
    }

    action set_multicast_group_action(bit<16> mcast_grp) {
        standard_metadata.mcast_grp = mcast_grp;
    }

    apply {
        build_flow_export_response_action();
#ifdef RF_TREE_COUNT
        build_analyzer_export_action();
        build_tenant_action();
#endif
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
        build_flow_record_action();
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
        build_biflow_record_action();
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

        if (meta.flow_export_reason == flow_export_reasons_t.UNCERTAIN_CLASSIFIED || meta.flow_export_reason == flow_export_reasons_t.ACTIVE_TIMEOUT_HIT || meta.flow_export_reason == flow_export_reasons_t.TCP_CONNECTION_FINISHED) {
            // set_multicast_group_action((bit<16>) standard_metadata.egress_spec);
            send_to_port_action(CPU_PORT);
        }
        if (meta.flow_export_reason == flow_export_reasons_t.INACTIVE_TIMEOUT_HIT) {
            send_to_port_action(CPU_PORT);
        }

        if (meta.flow_export_reason != flow_export_reasons_t.ACTIVE_TIMEOUT_HIT) {
            bloom_filter_flow_monitoring.write(meta.flow_hash, (bit<1>)0);
        }
    }
}