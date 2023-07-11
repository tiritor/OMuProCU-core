/*************************************************************************
************************* C O N T R O L **********************************
*************************************************************************/

#ifndef __FLOW_DATA_UPDATE__
#define __FLOW_DATA_UPDATE__

control FlowDataUpdater(inout headers_t hdr,
                       inout metadata_t meta,
                       inout standard_metadata_t standard_metadata) {

    
    action update_flow_data_action() {
        // flow packets and bytes counter (total)
        flow_packets_bytes_counter.count(meta.flow_hash);

        bit<32> bidirectional_bytes;
        bit<32> bidirectional_packets;

        // log_msg("src: {}:{}, dst: {}:{}", {hdr.ipv4.src_addr, meta.ingress_meta.l4_lookup.part1, hdr.ipv4.dst_addr, meta.ingress_meta.l4_lookup.part2});

        bidirectional_byte_register.read(bidirectional_bytes, meta.flow_hash);
        bidirectional_packet_register.read(bidirectional_packets, meta.flow_hash);
#if USE_PM
        bidirectional_bytes = bidirectional_bytes + hdr.pm.packet_length;
#else
        bidirectional_bytes = bidirectional_bytes + standard_metadata.packet_length;
#endif
        bidirectional_packets = bidirectional_packets + 1;
        meta.feature_meta.bidirectional_packets = bidirectional_packets;
        meta.feature_meta.bidirectional_bytes = bidirectional_bytes;

        bidirectional_byte_register.write(meta.flow_hash, bidirectional_bytes);
        bidirectional_packet_register.write(meta.flow_hash, bidirectional_packets);

        // log_msg("PCK - Bytes: {}", {meta.feature_meta.bidirectional_bytes});
        // log_msg("PM - timestamp: {}, packet_length: {}", {hdr.pm.timestamp, hdr.pm.packet_length});


#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
        // flow packet length (min, max, moving average)
        bit<FLOW_MONITORING_VALUE_WIDTH> flow_packet_length;
        
        // minimum
        flow_packet_length_min_register.read(flow_packet_length, meta.flow_hash);
#if USE_PM
        flow_packet_length = (flow_packet_length == 0 || hdr.pm.packet_length < flow_packet_length) ? hdr.pm.packet_length : flow_packet_length;
#else
        flow_packet_length = (flow_packet_length == 0 || standard_metadata.packet_length < flow_packet_length) ? standard_metadata.packet_length : flow_packet_length;
#endif
        meta.feature_meta.flow_packet_length_min = flow_packet_length;

        flow_packet_length_min_register.write(meta.flow_hash, flow_packet_length);
        
        // maximum
        flow_packet_length_max_register.read(flow_packet_length, meta.flow_hash);
#if USE_PM
        flow_packet_length =  (hdr.pm.packet_length > flow_packet_length) ? hdr.pm.packet_length : flow_packet_length;
#else
        flow_packet_length =  (standard_metadata.packet_length > flow_packet_length) ? standard_metadata.packet_length : flow_packet_length;
#endif
        meta.feature_meta.flow_packet_length_max = flow_packet_length;
        flow_packet_length_max_register.write(meta.flow_hash, flow_packet_length);
        
        // mean
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_packet_length_history;
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_packet_length_current;
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_packet_length_moving_average;
        flow_packet_length_mean_register.read(flow_packet_length, meta.flow_hash);
        flow_packet_length_history = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) flow_packet_length;
#if USE_PM
        flow_packet_length_current = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) hdr.pm.packet_length;
#else
        flow_packet_length_current = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) standard_metadata.packet_length;
#endif
        flow_packet_length_moving_average = (flow_packet_length != 0) ? ((flow_packet_length_history << MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH) - flow_packet_length_history + flow_packet_length_current) >> MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH : flow_packet_length_current;
        
        meta.feature_meta.flow_packet_length_mean = flow_packet_length_moving_average;

        flow_packet_length_mean_register.write(meta.flow_hash, (bit<FLOW_MONITORING_VALUE_WIDTH>)flow_packet_length_moving_average);

        // log_msg("LEN - packets_num: {}, actual: {}, min: {}, max: {}, mean: {}", {meta.feature_meta.bidirectional_packets, hdr.pm.packet_length, meta.feature_meta.flow_packet_length_min, meta.feature_meta.flow_packet_length_max, meta.feature_meta.flow_packet_length_mean});

         // flow packet inter-arrival time (min, max, moving average)
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_last_packet_timestamp;
        flow_last_packet_timestamp_register.read(flow_last_packet_timestamp, meta.flow_hash);
#if USE_PM
        flow_last_packet_timestamp_register.write(meta.flow_hash, hdr.pm.timestamp);
#else
        flow_last_packet_timestamp_register.write(meta.flow_hash, (bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp);
#endif
        // minimum
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_packet_inter_arrival_time;
        flow_packet_inter_arrival_time_min_register.read(flow_packet_inter_arrival_time, meta.flow_hash);

#if USE_PM
        flow_packet_inter_arrival_time = ((flow_packet_inter_arrival_time == 0 && flow_last_packet_timestamp != 0) || (hdr.pm.timestamp - flow_last_packet_timestamp) < flow_packet_inter_arrival_time) ? (hdr.pm.timestamp - flow_last_packet_timestamp) : flow_packet_inter_arrival_time;
#else
        flow_packet_inter_arrival_time = ((flow_packet_inter_arrival_time == 0 && flow_last_packet_timestamp != 0) || (((bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp) - flow_last_packet_timestamp) < flow_packet_inter_arrival_time ? (((bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp) - flow_last_packet_timestamp) : flow_packet_inter_arrival_time);
#endif

        meta.feature_meta.flow_packet_inter_arrival_time_min = flow_packet_inter_arrival_time;
        flow_packet_inter_arrival_time_min_register.write(meta.flow_hash, flow_packet_inter_arrival_time);

        // maximum
        flow_packet_inter_arrival_time_max_register.read(flow_packet_inter_arrival_time, meta.flow_hash);

#if USE_PM
        flow_packet_inter_arrival_time = ((flow_packet_inter_arrival_time == 0 && flow_last_packet_timestamp != 0) || (flow_packet_inter_arrival_time != 0 && ((hdr.pm.timestamp - flow_last_packet_timestamp) > flow_packet_inter_arrival_time))) ? (hdr.pm.timestamp - flow_last_packet_timestamp) : flow_packet_inter_arrival_time;
#else
        flow_packet_inter_arrival_time = ((flow_packet_inter_arrival_time == 0 && flow_last_packet_timestamp != 0) || (flow_packet_inter_arrival_time != 0 && (( ((bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp) - flow_last_packet_timestamp) > flow_packet_inter_arrival_time))) ? (((bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp) - flow_last_packet_timestamp) : flow_packet_inter_arrival_time;
#endif
        flow_packet_inter_arrival_time_max_register.write(meta.flow_hash, flow_packet_inter_arrival_time);
        meta.feature_meta.flow_packet_inter_arrival_time_max = flow_packet_inter_arrival_time;
        // mean
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_packet_inter_arrival_time_history;
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_packet_inter_arrival_time_current;
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_packet_inter_arrival_time_moving_average;
        flow_packet_inter_arrival_time_mean_register.read(flow_packet_inter_arrival_time, meta.flow_hash);
        flow_packet_inter_arrival_time_history = (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) flow_packet_inter_arrival_time;
#if USE_PM
        flow_packet_inter_arrival_time_current = (flow_last_packet_timestamp != 0 ) ? (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) (hdr.pm.timestamp - flow_last_packet_timestamp) : 0;
#else
        flow_packet_inter_arrival_time_current = (flow_last_packet_timestamp != 0 ) ? (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) (((bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp) - flow_last_packet_timestamp) : 0;
#endif
        flow_packet_inter_arrival_time_moving_average = (flow_packet_inter_arrival_time != 0) ? ((flow_packet_inter_arrival_time_history << MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH) - flow_packet_inter_arrival_time_history + flow_packet_inter_arrival_time_current) >> MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH : flow_packet_inter_arrival_time_current;
        
        meta.feature_meta.flow_packet_inter_arrival_time_mean = flow_packet_inter_arrival_time_moving_average;
        flow_packet_inter_arrival_time_mean_register.write(meta.flow_hash, (bit<FLOW_MONITORING_TIMESTAMP_WIDTH>)flow_packet_inter_arrival_time_moving_average);

        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> first_seen_timestamp;
        flow_first_packet_timestamp_register.read(first_seen_timestamp, meta.flow_hash);
        meta.feature_meta.flow_duration = hdr.pm.timestamp - first_seen_timestamp;

        // log_msg("IAT - packets_num: {}, actual: {}, min: {}, max: {}, mean: {}", {meta.feature_meta.bidirectional_packets, hdr.pm.timestamp - flow_last_packet_timestamp, meta.feature_meta.flow_packet_inter_arrival_time_min, meta.feature_meta.flow_packet_inter_arrival_time_max, meta.feature_meta.flow_packet_inter_arrival_time_mean});

#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
    }


#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    bit<8> flow_direction;

    action determine_flow_direction() {
        ipv4_address_t registered_src_ip_address;
        ipv4_address_t registered_dst_ip_address;

        flow_src_ip_register.read(registered_src_ip_address, meta.flow_hash);
        flow_dst_ip_register.read(registered_dst_ip_address, meta.flow_hash);

        flow_direction = (registered_src_ip_address == hdr.ipv4.src_addr && registered_dst_ip_address == hdr.ipv4.dst_addr) ? flow_direction_t.FORWARD : flow_direction_t.BACKWARD;
    }

    action update_flow_forward_data_action() {
        // biflow forward packet and byte counter (total)
        flow_forward_packets_bytes_counter.count(meta.flow_hash);

        // biflow forward packet length (min, max, moving average)
        bit<FLOW_MONITORING_VALUE_WIDTH> flow_forward_packet_length;
        
        // minimum
        flow_forward_packet_length_min_register.read(flow_forward_packet_length, meta.flow_hash);
#if USE_PM
        flow_forward_packet_length = (flow_forward_packet_length == 0 || hdr.pm.packet_length < flow_forward_packet_length) ? hdr.pm.packet_length : flow_forward_packet_length;
#else
        flow_forward_packet_length = (flow_forward_packet_length == 0 || standard_metadata.packet_length < flow_forward_packet_length) ? standard_metadata.packet_length : flow_forward_packet_length;
#endif
        meta.feature_meta.forward_packet_length_min = flow_forward_packet_length;

        flow_forward_packet_length_min_register.write(meta.flow_hash, flow_forward_packet_length);
        
        // maximum
        flow_forward_packet_length_max_register.read(flow_forward_packet_length, meta.flow_hash);
#if USE_PM
        flow_forward_packet_length = (hdr.pm.packet_length > flow_forward_packet_length) ? hdr.pm.packet_length : flow_forward_packet_length;
#else
        flow_forward_packet_length = (standard_metadata.packet_length > flow_forward_packet_length) ? standard_metadata.packet_length : flow_forward_packet_length;
#endif
        meta.feature_meta.forward_packet_length_max = flow_forward_packet_length;
        
        flow_forward_packet_length_max_register.write(meta.flow_hash, flow_forward_packet_length);
        
        // mean
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_forward_packet_length_history;
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_forward_packet_length_current;
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_forward_packet_length_moving_average;
        flow_forward_packet_length_mean_register.read(flow_forward_packet_length, meta.flow_hash);
        flow_forward_packet_length_history = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) flow_forward_packet_length;
#if USE_PM
        flow_forward_packet_length_current = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) hdr.pm.packet_length;
#else
        flow_forward_packet_length_current = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) standard_metadata.packet_length;
#endif
        flow_forward_packet_length_moving_average = (flow_forward_packet_length != 0) ? ((flow_forward_packet_length_history << MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH) - flow_forward_packet_length_history + flow_forward_packet_length_current) >> MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH : flow_forward_packet_length_current;

        meta.feature_meta.forward_packet_length_mean = flow_forward_packet_length_moving_average;

        flow_forward_packet_length_mean_register.write(meta.flow_hash, (bit<FLOW_MONITORING_VALUE_WIDTH>)flow_forward_packet_length_moving_average);

        bit<32> forward_packets;
        bit<32> forward_bytes;
        // bit<16> fwd_ack_flags;

        forward_byte_register.read(forward_bytes, meta.flow_hash);
        forward_packet_register.read(forward_packets, meta.flow_hash);
        // fwd_ack_flag_register.read(fwd_ack_flags, meta.flow_hash);
        
#if USE_PM
        forward_bytes = forward_bytes + hdr.pm.packet_length;
#else
        forward_bytes = forward_bytes + standard_metadata.packet_length;
#endif
        forward_packets = forward_packets + 1;

        // fwd_ack_flags = ((hdr.tcp.flags & tcp_flags_t.ACK) == tcp_flags_t.ACK) ? fwd_ack_flags + 1: fwd_ack_flags; // Not needed at the moment

        // Updating feature metadata
        meta.feature_meta.forward_bytes = forward_bytes;
        meta.feature_meta.forward_packets = forward_packets;
     

        // fwd_ack_flag_register.write(meta.flow_hash, fwd_ack_flags);
        forward_byte_register.write(meta.flow_hash, forward_bytes);
        forward_packet_register.write(meta.flow_hash, forward_packets);

        // biflow forward packet inter-arrival time (min, max, moving average)
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_forward_last_packet_timestamp;
        flow_forward_last_packet_timestamp_register.read(flow_forward_last_packet_timestamp, meta.flow_hash);
#if USE_PM
        flow_forward_last_packet_timestamp_register.write(meta.flow_hash, hdr.pm.timestamp);
#else
        flow_forward_last_packet_timestamp_register.write(meta.flow_hash, (bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp);
#endif
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_forward_packet_inter_arrival_time;
        // minimum
        flow_forward_packet_inter_arrival_time_min_register.read(flow_forward_packet_inter_arrival_time, meta.flow_hash);
#if USE_PM
        flow_forward_packet_inter_arrival_time = (flow_forward_packet_inter_arrival_time == 0 || (hdr.pm.timestamp - flow_forward_last_packet_timestamp) <= flow_forward_packet_inter_arrival_time) ? (hdr.pm.timestamp - flow_forward_last_packet_timestamp) : flow_forward_packet_inter_arrival_time;
#else
        flow_forward_packet_inter_arrival_time = (flow_forward_packet_inter_arrival_time == 0 || (standard_metadata.ingress_global_timestamp - flow_forward_last_packet_timestamp) <= flow_forward_packet_inter_arrival_time) ? (standard_metadata.ingress_global_timestamp - flow_forward_last_packet_timestamp) : flow_forward_packet_inter_arrival_time;
#endif
        meta.feature_meta.flow_fwd_packet_inter_arrival_time_min = flow_forward_packet_inter_arrival_time;
        flow_forward_packet_inter_arrival_time_min_register.write(meta.flow_hash, flow_forward_packet_inter_arrival_time);
        // maximum
        flow_forward_packet_inter_arrival_time_max_register.read(flow_forward_packet_inter_arrival_time, meta.flow_hash);

#if USE_PM
        flow_forward_packet_inter_arrival_time = ((flow_forward_packet_inter_arrival_time == 0 && flow_forward_last_packet_timestamp != 0) || (flow_forward_packet_inter_arrival_time != 0 && ((hdr.pm.timestamp - flow_forward_last_packet_timestamp) > flow_forward_packet_inter_arrival_time))) ? (hdr.pm.timestamp - flow_forward_last_packet_timestamp) : flow_forward_packet_inter_arrival_time;
#else
        flow_forward_packet_inter_arrival_time = ((flow_forward_packet_inter_arrival_time == 0 && flow_forward_last_packet_timestamp != 0) || (flow_forward_packet_inter_arrival_time != 0 && ((standard_metadata.ingress_global_timestamp - flow_forward_last_packet_timestamp) > flow_forward_packet_inter_arrival_time))) ? (standard_metadata.ingress_global_timestamp - flow_forward_last_packet_timestamp) : flow_forward_packet_inter_arrival_time;
#endif

        meta.feature_meta.flow_fwd_packet_inter_arrival_time_max = flow_forward_packet_inter_arrival_time;
        flow_forward_packet_inter_arrival_time_max_register.write(meta.flow_hash, flow_forward_packet_inter_arrival_time);
        // mean
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_forward_packet_inter_arrival_time_history;
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_forward_packet_inter_arrival_time_current;
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_forward_packet_inter_arrival_time_moving_average;
        flow_forward_packet_inter_arrival_time_mean_register.read(flow_forward_packet_inter_arrival_time, meta.flow_hash);
        flow_forward_packet_inter_arrival_time_history = (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) flow_forward_packet_inter_arrival_time;
        flow_forward_packet_inter_arrival_time_current = (flow_forward_last_packet_timestamp != 0 ) ? (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) ((bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp - flow_forward_last_packet_timestamp) : 0;
        flow_forward_packet_inter_arrival_time_moving_average = (flow_forward_packet_inter_arrival_time != 0) ? ((flow_forward_packet_inter_arrival_time_history << MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH) - flow_forward_packet_inter_arrival_time_history + flow_forward_packet_inter_arrival_time_current) >> MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH : flow_forward_packet_inter_arrival_time_current;

        meta.feature_meta.flow_fwd_packet_inter_arrival_time_mean = flow_forward_packet_inter_arrival_time_moving_average;
        flow_forward_packet_inter_arrival_time_mean_register.write(meta.flow_hash, (bit<FLOW_MONITORING_TIMESTAMP_WIDTH>)flow_forward_packet_inter_arrival_time_moving_average);

    }



    action update_flow_backward_data_action() {
        // biflow backward packets and bytes counter (total)
        flow_backward_packets_bytes_counter.count(meta.flow_hash);


        // biflow backward packet length (min, max, moving average)
        bit<FLOW_MONITORING_VALUE_WIDTH> flow_backward_packet_length;
        // minimum
        flow_backward_packet_length_min_register.read(flow_backward_packet_length, meta.flow_hash);

#if USE_PM
        flow_backward_packet_length = (flow_backward_packet_length == 0 || hdr.pm.packet_length < flow_backward_packet_length) ? hdr.pm.packet_length : flow_backward_packet_length;
#else
        flow_backward_packet_length = (flow_backward_packet_length == 0 || standard_metadata.packet_length < flow_backward_packet_length) ? standard_metadata.packet_length : flow_backward_packet_length;
#endif
        meta.feature_meta.backward_packet_length_min = flow_backward_packet_length;

        flow_backward_packet_length_min_register.write(meta.flow_hash, flow_backward_packet_length);
        // maximum
        flow_backward_packet_length_max_register.read(flow_backward_packet_length, meta.flow_hash);
#if USE_PM
        flow_backward_packet_length = (hdr.pm.packet_length > flow_backward_packet_length) ? hdr.pm.packet_length : flow_backward_packet_length;
#else
        flow_backward_packet_length = (standard_metadata.packet_length > flow_backward_packet_length) ? standard_metadata.packet_length : flow_backward_packet_length;
#endif
        meta.feature_meta.backward_packet_length_max = flow_backward_packet_length;

        flow_backward_packet_length_max_register.write(meta.flow_hash, flow_backward_packet_length);
        // mean
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_backward_packet_length_history;
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_backward_packet_length_current;
        bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_backward_packet_length_moving_average;
        flow_backward_packet_length_mean_register.read(flow_backward_packet_length, meta.flow_hash);
        flow_backward_packet_length_history = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) flow_backward_packet_length;
#if USE_PM
        flow_backward_packet_length_current = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) hdr.pm.packet_length;
#else
        flow_backward_packet_length_current = (bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED>) standard_metadata.packet_length;
#endif
        flow_backward_packet_length_moving_average = (flow_backward_packet_length != 0) ? ((flow_backward_packet_length_history << MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH) - flow_backward_packet_length_history + flow_backward_packet_length_current) >> MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH : flow_backward_packet_length_current;

        meta.feature_meta.backward_packet_length_mean = flow_backward_packet_length_moving_average;

        flow_backward_packet_length_mean_register.write(meta.flow_hash, (bit<FLOW_MONITORING_VALUE_WIDTH>)flow_backward_packet_length_moving_average);

        
        bit<32> backward_packets;
        bit<32> backward_bytes;

        backward_byte_register.read(backward_bytes, meta.flow_hash);
        backward_packet_register.read(backward_packets, meta.flow_hash);
        
#if USE_PM
        backward_bytes = backward_bytes + hdr.pm.packet_length;
#else
        backward_bytes = backward_bytes + standard_metadata.packet_length;
#endif
        backward_packets = backward_packets + 1;

        // Updating feature metadata
        meta.feature_meta.backward_bytes = backward_bytes;
        meta.feature_meta.backward_packets = backward_packets;

        backward_byte_register.write(meta.flow_hash, backward_bytes);
        backward_packet_register.write(meta.flow_hash, backward_packets);

        // biflow backward packet inter-arrival time (min, max, moving average)
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_backward_last_packet_timestamp;
        flow_backward_last_packet_timestamp_register.read(flow_backward_last_packet_timestamp, meta.flow_hash);
#if USE_PM
        flow_backward_last_packet_timestamp_register.write(meta.flow_hash, hdr.pm.timestamp);
#else
        flow_backward_last_packet_timestamp_register.write(meta.flow_hash, standard_metadata.ingress_global_timestamp);
#endif
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_backward_packet_inter_arrival_time;
        // minimum
        flow_backward_packet_inter_arrival_time_min_register.read(flow_backward_packet_inter_arrival_time, meta.flow_hash);
#if USE_PM
        flow_backward_packet_inter_arrival_time = ((flow_backward_packet_inter_arrival_time == 0 && flow_backward_last_packet_timestamp != 0) || (hdr.pm.timestamp - flow_backward_last_packet_timestamp) <= flow_backward_packet_inter_arrival_time) ? (hdr.pm.timestamp - flow_backward_last_packet_timestamp) : flow_backward_packet_inter_arrival_time;
#else
        flow_backward_packet_inter_arrival_time = ((flow_backward_packet_inter_arrival_time == 0 && flow_backward_last_packet_timestamp != 0) || (standard_metadata.ingress_global_timestamp - flow_backward_last_packet_timestamp) <= flow_backward_packet_inter_arrival_time) ? (standard_metadata.ingress_global_timestamp - flow_backward_last_packet_timestamp) : flow_backward_packet_inter_arrival_time;
#endif
        flow_backward_packet_inter_arrival_time_min_register.write(meta.flow_hash, flow_backward_packet_inter_arrival_time);
        // maximum
        flow_backward_packet_inter_arrival_time_max_register.read(flow_backward_packet_inter_arrival_time, meta.flow_hash);
#if USE_PM
        flow_backward_packet_inter_arrival_time = ((flow_backward_packet_inter_arrival_time == 0 && flow_backward_last_packet_timestamp != 0) || (flow_backward_packet_inter_arrival_time != 0 && ((hdr.pm.timestamp - flow_backward_last_packet_timestamp) > flow_backward_packet_inter_arrival_time))) ? (hdr.pm.timestamp - flow_backward_last_packet_timestamp) : flow_backward_packet_inter_arrival_time;
#else
        flow_backward_packet_inter_arrival_time = ((flow_backward_packet_inter_arrival_time == 0 && flow_backward_last_packet_timestamp != 0) || (flow_backward_packet_inter_arrival_time != 0 && ((standard_metadata.ingress_global_timestamp - flow_backward_last_packet_timestamp) > flow_backward_packet_inter_arrival_time))) ? (standard_metadata.ingress_global_timestamp - flow_backward_last_packet_timestamp) : flow_backward_packet_inter_arrival_time;
#endif
        flow_backward_packet_inter_arrival_time_max_register.write(meta.flow_hash, flow_backward_packet_inter_arrival_time);
        // mean
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_backward_packet_inter_arrival_time_history;
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_backward_packet_inter_arrival_time_current;
        bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_backward_packet_inter_arrival_time_moving_average;
        flow_backward_packet_inter_arrival_time_mean_register.read(flow_backward_packet_inter_arrival_time, meta.flow_hash);
        flow_backward_packet_inter_arrival_time_history = (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) flow_backward_packet_inter_arrival_time;
#if USE_PM
        flow_backward_packet_inter_arrival_time_current = (flow_backward_last_packet_timestamp != 0 ) ? (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) (hdr.pm.timestamp - flow_backward_last_packet_timestamp) : 0;
#else
        flow_backward_packet_inter_arrival_time_current = (flow_backward_last_packet_timestamp != 0 ) ? (bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED>) (standard_metadata.ingress_global_timestamp - flow_backward_last_packet_timestamp) : 0;
#endif
        flow_backward_packet_inter_arrival_time_moving_average = (flow_backward_packet_inter_arrival_time != 0) ? ((flow_backward_packet_inter_arrival_time_history << MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH) - flow_backward_packet_inter_arrival_time_history + flow_backward_packet_inter_arrival_time_current) >> MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH : flow_backward_packet_inter_arrival_time_current;
        flow_backward_packet_inter_arrival_time_mean_register.write(meta.flow_hash, (bit<FLOW_MONITORING_TIMESTAMP_WIDTH>)flow_backward_packet_inter_arrival_time_moving_average);
    }

#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

    apply {

        last_timestamp_register.write(0, hdr.pm.timestamp);
        update_flow_data_action();

        if (meta.feature_meta.bidirectional_packets == 1) {
#if USE_PM
            // time_t first_seen_timestamp = hdr.pm.timestamp;
            flow_first_packet_timestamp_register.write(meta.flow_hash, hdr.pm.timestamp);
#else
            // time_t first_seen_timestamp = standard_metadata.ingress_global_timestamp;
            flow_first_packet_timestamp_register.write(meta.flow_hash, (bit<FLOW_MONITORING_TIMESTAMP_WIDTH>) standard_metadata.ingress_global_timestamp);
#endif 
            // flow_first_packet_timestamp_register.write(meta.flow_hash, first_seen_timestamp);
        }


#if (defined(FLOW_TYPE_BIFLOWS))
        determine_flow_direction();

        if (flow_direction == flow_direction_t.FORWARD) {
            update_flow_forward_data_action();

        if (meta.feature_meta.forward_packets == 1) {
#if USE_PM
            flow_forward_first_packet_timestamp_register.write(meta.flow_hash, hdr.pm.timestamp);
            // time_t first_seen_timestamp = hdr.pm.timestamp;
#else
            flow_forward_first_packet_timestamp_register.write(meta.flow_hash, standard_metadata.ingress_global_timestamp);
            // time_t first_seen_timestamp = standard_metadata.ingress_global_timestamp;
#endif
            // flow_forward_first_packet_timestamp_register.write(meta.flow_hash, first_seen_timestamp);
            }
        }

        if (flow_direction == flow_direction_t.BACKWARD) {
            update_flow_backward_data_action();

            if (meta.feature_meta.backward_packets == 1) {
#if USE_PM
            // time_t first_seen_timestamp = hdr.pm.timestamp;
            flow_backward_first_packet_timestamp_register.write(meta.flow_hash, hdr.pm.timestamp);
#else
            // time_t first_seen_timestamp = standard_metadata.ingress_global_timestamp;
            flow_backward_first_packet_timestamp_register.write(meta.flow_hash, standard_metadata.ingress_global_timestamp);
#endif
            // flow_backward_first_packet_timestamp_register.write(meta.flow_hash, first_seen_timestamp);
            }
        }
#endif  // (defined(FLOW_TYPE_BIFLOWS))

    }

}

#endif // __FLOW_DATA_UPDATE__