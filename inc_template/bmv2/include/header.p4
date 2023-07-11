/*************************************************************************
*********************** H E A D E R S / T Y P E S ************************
*************************************************************************/

#ifndef __TYPES__
#define __TYPES__

#define FLOW_MONITORING_VALUE_WIDTH 32
#define FLOW_MONITORING_TIMESTAMP_WIDTH 56

#ifdef FLOW_TYPE_FLOWS
#define NODE_COUNT 750
#elif defined(FLOW_TYPE_BIFLOWS)
#define NODE_COUNT 1000
#endif 

typedef bit<16> ether_type_t;
typedef bit<48> mac_address_t;
typedef bit<32> ipv4_address_t;
typedef bit<8>  ipv4_protocol_t;
typedef bit<16> l4_port_t;
typedef bit<9>  port_id_t;

// typedef bit<16> flow_hash_t;
typedef bit<32> flow_hash_t;

typedef bit<FLOW_MONITORING_VALUE_WIDTH> packet_count_t;
typedef bit<FLOW_MONITORING_VALUE_WIDTH> packet_length_t;
typedef bit<FLOW_MONITORING_VALUE_WIDTH> byte_count_t;
typedef bit<FLOW_MONITORING_TIMESTAMP_WIDTH> time_t;
typedef bit<64> time_t_extended;

const ether_type_t ETHERTYPE_IPV4 = 0x0800;
const ether_type_t ETHERTYPE_FLOW_MONITORING = 0x4242;
const ether_type_t ETHERTYPE_FLOW_EXPORT_REQUEST = 0x2121;
const ether_type_t ETHERTYPE_FLOW_EXPORT_RESPONSE = 0x1212;
enum bit<16> ether_types_t {
    IPV4                 = ETHERTYPE_IPV4,
    FLOW_MONITORING      = ETHERTYPE_FLOW_MONITORING,
    FLOW_EXPORT_REQUEST  = ETHERTYPE_FLOW_EXPORT_REQUEST,
    FLOW_EXPORT_RESPONSE = ETHERTYPE_FLOW_EXPORT_RESPONSE
}

const mac_address_t FLOW_EXPORT_REQUEST_PACKET_SRC_MAC = 0x212121212121;
const mac_address_t FLOW_EXPORT_REQUEST_PACKET_DST_MAC = 0x424242424242;

#endif  // __TYPES__

#ifndef __HEADER__
#define __HEADER__

header ethernet_h {
    mac_address_t dst_addr;
    mac_address_t src_addr;
    ether_type_t  ether_type;
}
const bit<16> ETHERNET_H_LENGTH = 14;

header ipv4_h {
    bit<4>          version;
    bit<4>          ihl;
    bit<8>          tos;
    bit<16>         total_length;
    bit<16>         identification;
    bit<3>          flags;
    bit<13>         frag_offset;
    bit<8>          ttl;
    ipv4_protocol_t protocol;
    bit<16>         hdr_checksum;
    ipv4_address_t  src_addr;
    ipv4_address_t  dst_addr;
}

header ipv4_options_h {
    varbit<320> options;
}

header icmp_h {
    bit<8>  type;
    bit<8>  code;
    bit<16> checksum;
}

header tcp_h {
    l4_port_t src_port;
    l4_port_t dst_port;
    bit<32>   seq_num;
    bit<32>   ack_num;
    bit<4>    data_offset;
    bit<4>    reserved;
    bit<8>    flags;
    bit<16>   window;
    bit<16>   checksum;
    bit<16>   urgent_ptr;
}

header tcp_options_h {
    varbit<320> options;
}

header udp_h {
    l4_port_t src_port;
    l4_port_t dst_port;
    bit<16>   len;
    bit<16>   checksum;
}

header vxlan_h {
    bit<8>  flags;
    bit<24> reserved;
    bit<24> vni;
    bit<8>  reserved_2;
}

header pm_h {
    packet_length_t packet_length;
    time_t timestamp;
}

header flow_monitoring_h {
    flow_hash_t flow_hash;
    bit<8> message_reason;
    // bit<8>      flow_type;
}

header tenant_h {
    bit<24> tenant_id;
    bit<8> tenant_func_id;
}
const bit<16> TENANT_H_DATA_LENGTH = 3;

header analyzer_h {
    bit<16> class;
    bit<64> probability;
    bit<16> malware;
    bit<16> tree_count;
}
const bit<16> ANALYZER_DATA_H_LENGTH = 14;


#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
header flow_record_data_h {
    // general properties
    bit<8>           export_condition;
    bit<16>          reserved;
    // flow 5-tuple
    ipv4_protocol_t  ip_protocol;
    ipv4_address_t   src_ip;
    ipv4_address_t   dst_ip;
    l4_port_t        src_port;
    l4_port_t        dst_port;
    // flow properties
    // time_t           start;
    // time_t           end;
    time_t_extended  start;
    time_t_extended  end;
    packet_count_t   packets;
    byte_count_t     bytes;
    // tcp_flags_mask_t tcp_flags;
    // tcp_flag_count_t tcp_flags_FIN_count;
    // tcp_flag_count_t tcp_flags_SYN_count;
    // tcp_flag_count_t tcp_flags_RST_count;
    // tcp_flag_count_t tcp_flags_PSH_count;
    // tcp_flag_count_t tcp_flags_ACK_count;
    // tcp_flag_count_t tcp_flags_URG_count;
    // tcp_flag_count_t tcp_flags_ECE_count;
    // tcp_flag_count_t tcp_flags_CWR_count;
    packet_length_t  packet_length_min;
    packet_length_t  packet_length_max;
    packet_length_t  packet_length_mean;
    // time_t           packet_inter_arrival_time_min;
    // time_t           packet_inter_arrival_time_max;
    // time_t           packet_inter_arrival_time_mean;
    time_t_extended  packet_inter_arrival_time_min;
    time_t_extended  packet_inter_arrival_time_max;
    time_t_extended  packet_inter_arrival_time_mean;
}

// const bit<16> FLOW_RECORD_DATA_H_LENGTH = 83;
// const bit<16> FLOW_RECORD_DATA_H_LENGTH = 93;
const bit<16> FLOW_RECORD_DATA_H_LENGTH = 76;

#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))

#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
header biflow_record_data_h {
    // general properties
    bit<8>           export_condition;
    bit<16>          reserved;
    // flow 5-tuple
    ipv4_protocol_t  ip_protocol;
    ipv4_address_t   src_ip;
    ipv4_address_t   dst_ip;
    l4_port_t        src_port;
    l4_port_t        dst_port;
    // forward flow properties
    // time_t           forward_start;
    // time_t           forward_end;
    time_t_extended  forward_start;
    time_t_extended  forward_end;
    packet_count_t   forward_packets;
    byte_count_t     forward_bytes;
    // tcp_flags_mask_t forward_tcp_flags;
    // tcp_flag_count_t forward_tcp_flags_FIN_count;
    // tcp_flag_count_t forward_tcp_flags_SYN_count;
    // tcp_flag_count_t forward_tcp_flags_RST_count;
    // tcp_flag_count_t forward_tcp_flags_PSH_count;
    // tcp_flag_count_t forward_tcp_flags_ACK_count;
    // tcp_flag_count_t forward_tcp_flags_URG_count;
    // tcp_flag_count_t forward_tcp_flags_ECE_count;
    // tcp_flag_count_t forward_tcp_flags_CWR_count;
    packet_length_t  forward_packet_length_min;
    packet_length_t  forward_packet_length_max;
    packet_length_t  forward_packet_length_mean;
    // time_t           forward_packet_inter_arrival_time_min;
    // time_t           forward_packet_inter_arrival_time_max;
    // time_t           forward_packet_inter_arrival_time_mean;
    time_t_extended  forward_packet_inter_arrival_time_min;
    time_t_extended  forward_packet_inter_arrival_time_max;
    time_t_extended  forward_packet_inter_arrival_time_mean;
    // backward flow properties
    // time_t           backward_start;
    // time_t           backward_end;
    time_t_extended  backward_start;
    time_t_extended  backward_end;
    packet_count_t   backward_packets;
    byte_count_t     backward_bytes;
    // tcp_flags_mask_t backward_tcp_flags;
    // tcp_flag_count_t backward_tcp_flags_FIN_count;
    // tcp_flag_count_t backward_tcp_flags_SYN_count;
    // tcp_flag_count_t backward_tcp_flags_RST_count;
    // tcp_flag_count_t backward_tcp_flags_PSH_count;
    // tcp_flag_count_t backward_tcp_flags_ACK_count;
    // tcp_flag_count_t backward_tcp_flags_URG_count;
    // tcp_flag_count_t backward_tcp_flags_ECE_count;
    // tcp_flag_count_t backward_tcp_flags_CWR_count;
    packet_length_t  backward_packet_length_min;
    packet_length_t  backward_packet_length_max;
    packet_length_t  backward_packet_length_mean;
    // time_t           backward_packet_inter_arrival_time_min;
    // time_t           backward_packet_inter_arrival_time_max;
    // time_t           backward_packet_inter_arrival_time_mean;
    time_t_extended  backward_packet_inter_arrival_time_min;
    time_t_extended  backward_packet_inter_arrival_time_max;
    time_t_extended  backward_packet_inter_arrival_time_mean;
}


// const bit<16> BIFLOW_RECORD_DATA_H_LENGTH = 146;
// const bit<16> BIFLOW_RECORD_DATA_H_LENGTH = 170;
const bit<16> BIFLOW_RECORD_DATA_H_LENGTH = 136;

#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

header flow_export_request_h {
    flow_hash_t flow_hash;
    bit<8>      flow_type;    
}   // 5 bytes

header flow_export_response_h {
    flow_hash_t flow_hash;
    bit<8>      flow_type;
}
const bit<16> FLOW_EXPORT_RESPONSE_H_LENGTH = 5;
#endif  // FLOW_EXPORT_STRATEGY_EXPORT_PACKETS

struct l4_lookup_t {
    l4_port_t part1;
    l4_port_t part2;
}

struct parser_metadata_t {
}

struct ingress_metadata_t {
    l4_lookup_t l4_lookup;
    l4_lookup_t inner_l4_lookup;
    bit<1> flow_hash_collision;
    // bit<1> flow_hash_2_collision;
}

struct tenant_metadata_t {
    bit<24> tenant_id;
    bit<8> tenant_func_id;
    bit<1> export_flag;
}

struct l4_metadata_t {
    l4_port_t src_port;
    l4_port_t dst_port;
}

struct egress_metadata_t {
}

struct feature_metadata_t {
    bit<64> feature1;
    bit<64> feature2;
    bit<64> feature3;
    bit<64> feature4;
    bit<64> feature5;
    bit<64> feature6;
    bit<64> feature7;
    bit<64> feature8;
    bit<64> feature9;
    bit<64> feature10;
    bit<64> feature11;
    bit<64> feature12;
    bit<64> feature13;
#ifdef FLOW_TYPE_BIFLOWS
    bit<64> feature14;
    bit<64> feature15;
    bit<64> feature16;
    bit<64> feature17;
    bit<64> feature18;
    bit<64> feature19;
    bit<64> feature20;
    bit<64> feature21;
    bit<64> feature22;
    bit<64> feature23;
    bit<64> feature24;
    bit<64> feature25;
    bit<64> feature26;
    bit<64> feature27;
#endif
    bit<16> prevFeature;
    bit<16> isTrue;
    bit<16> class;
    bit<1> wednesday_timeframe;
    bit<1> friday_timeframe;
    // bit<1> timeframe;
    bit<16> node_id;

    bit<16> tree_count;

    bool uncertain;

#ifdef RF_TREE_COUNT
// #if RF_TREE_COUNT == 1
//    bit<8> probability;
// #elif RF_TREE_COUNT == 4 || RF_TREE_COUNT == 8
    bit<64> probability;
    bit<16> node_id_0;
    bit<16> node_id_1;
    bit<16> node_id_2;
    bit<16> node_id_3;
    bit<16> class_0;
    bit<16> class_1;
    bit<16> class_2;
    bit<16> class_3;
    bit<64> probability_0;
    bit<64> probability_1;
    bit<64> probability_2;
    bit<64> probability_3;
// #if RF_TREE_COUNT == 8
    bit<16> node_id_4;
    bit<16> node_id_5;
    bit<16> node_id_6;
    bit<16> node_id_7;
    bit<16> class_4;
    bit<16> class_5;
    bit<16> class_6;
    bit<16> class_7;
    bit<64> probability_4;
    bit<64> probability_5;
    bit<64> probability_6;
    bit<64> probability_7;
// #endif
// #endif
#endif

    // bit<1> direction;
    // bit<32> register_index;
    // bit<32> register_index_2;
    // bit<32> register_index_inverse;
    // bit<32> register_index_inverse_2;

 
    // Unused Features
    l4_port_t       dst_port; 
    
    
    // Used Features

    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_packet_inter_arrival_time_min;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_packet_inter_arrival_time_max;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_packet_inter_arrival_time_mean;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_duration; // duration in µs = end - start
    
    // bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_fwd_packet_inter_arrival_time_min;
    // bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_fwd_packet_inter_arrival_time_max;
    // bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_fwd_packet_inter_arrival_time_mean;

    // bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_bwd_packet_inter_arrival_time_min;
    // bit<FLOW_MONITORING_TIMESTAMP_WIDTH> flow_bwd_packet_inter_arrival_time_max;
    // bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> flow_bwd_packet_inter_arrival_time_mean;

    packet_count_t  bidirectional_packets;
    byte_count_t    bidirectional_bytes; // = flow_total_length_packets
    packet_length_t flow_packet_length_min;
    packet_length_t flow_packet_length_max;
    bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> flow_packet_length_mean;

    packet_count_t  flow_avg_num_packets; // = flow.bidirectional_bytes / flow.bidirectional_packets
    packet_count_t  fwd_avg_num_packets;  // = src2dst_bytes / src2dst_packets

    // packet_count_t pps; // = bytes / (duration in µs / 1000000)
    // byte_count_t bps; // = packets / (duration in µs / 1000000)

#if defined(FLOW_TYPE_BIFLOWS)

    packet_count_t  forward_packets;
    byte_count_t    forward_bytes; // = forward_total_length_packets
    packet_length_t forward_packet_length_min;
    packet_length_t forward_packet_length_max;
    bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> forward_packet_length_mean;

    packet_count_t  backward_packets; 
    byte_count_t    backward_bytes; // = backward_total_length_packets
    packet_length_t backward_packet_length_max;
    bit<FLOW_MONITORING_VALUE_WIDTH_EXTENDED> backward_packet_length_mean;
    packet_length_t backward_packet_length_min;


    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> backward_flow_packet_inter_arrival_time_min;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> backward_flow_packet_inter_arrival_time_max;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> backward_flow_packet_inter_arrival_time_mean;

    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> forward_flow_packet_inter_arrival_time_min;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH> forward_flow_packet_inter_arrival_time_max;
    bit<FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED> forward_flow_packet_inter_arrival_time_mean;

#endif

    bit<1> malware;
    bit<1> marked_malware;
}

struct metadata_t {
    @field_list(CLONE_FL_1)
    flow_hash_t flow_hash;
#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
    @field_list(CLONE_FL_1)
    bit<8>      flow_type;
    @field_list(CLONE_FL_1)
    bit<8>      flow_export_reason;
#endif
    @field_list(CLONE_FL_1)
    parser_metadata_t  parser_meta;
    @field_list(CLONE_FL_1)
    ingress_metadata_t ingress_meta;
    @field_list(CLONE_FL_1)
    egress_metadata_t  egress_meta;
    @field_list(CLONE_FL_1)
    feature_metadata_t feature_meta;
    @field_list(CLONE_FL_1)
    tenant_metadata_t tenant_meta;
    @field_list(CLONE_FL_1)
    l4_metadata_t l4_meta;

}

// const bit<16> FLOW_RECORD_DATA_H_LENGTH = 83;
// const bit<16> FLOW_RECORD_DATA_H_LENGTH = 93;


// const bit<16> BIFLOW_RECORD_DATA_H_LENGTH = 153;
// const bit<16> BIFLOW_RECORD_DATA_H_LENGTH = 177;

// const bit<16> BISUBFLOW_RECORD_DATA_H_LENGTH = (2 * (5 * SUBFLOW_VALUES_WIDTH + 3 * SUBFLOW_TIMESTAMPS_WIDTH)) >> 3;

struct headers_t {
    ethernet_h     ethernet;
    ipv4_h         ipv4;
    ipv4_options_h ipv4_options;
    icmp_h         icmp;
    tcp_h          tcp;
    tcp_options_h  tcp_options;
    udp_h          udp;
    pm_h           pm;
    vxlan_h        vxlan;
    ethernet_h     inner_ethernet;
    ipv4_h         inner_ipv4;
    icmp_h         inner_icmp;
    tcp_h          inner_tcp;
    tcp_options_h  inner_tcp_options;
    udp_h          inner_udp;
    flow_monitoring_h flow_mon;
    tenant_h        tenant;
    flow_export_request_h  flow_export_request;
    flow_export_response_h flow_export_response;
#if defined(FLOW_TYPE_FLOWS) 
    flow_record_data_h  flow_record_data;
#endif  // defined(FLOW_TYPE_FLOWS) 
#if defined(FLOW_TYPE_BIFLOWS) 
    biflow_record_data_h biflow_record_data;
#endif  // defined(FLOW_TYPE_BIFLOWS) 
    analyzer_h      analyzer;
}

#endif  // __HEADER__
