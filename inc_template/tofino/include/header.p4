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

typedef bit<32> flow_hash_t;

typedef bit<FLOW_MONITORING_VALUE_WIDTH> packet_count_t;
typedef bit<FLOW_MONITORING_VALUE_WIDTH> packet_length_t;
typedef bit<FLOW_MONITORING_VALUE_WIDTH> byte_count_t;
typedef bit<FLOW_MONITORING_TIMESTAMP_WIDTH> time_t;
typedef bit<64> time_t_extended;

const ether_type_t ETHERTYPE_IPV4 = 0x0800;
const ether_type_t ETHERTYPE_ARP = 0x0806;
const ether_type_t ETHERTYPE_FLOW_MONITORING = 0x4242;
const ether_type_t ETHERTYPE_FLOW_EXPORT_REQUEST = 0x2121;
const ether_type_t ETHERTYPE_FLOW_EXPORT_RESPONSE = 0x1212;
enum bit<16> ether_types_t {
    IPV4                 = ETHERTYPE_IPV4,
    ARP                  = ETHERTYPE_ARP,
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

header arp_h {
    bit<16> hrd; // Hardware Type
    bit<16> pro; // Protocol Type
    bit<8> hln; // Hardware Address Length
    bit<8> pln; // Protocol Address Length
    bit<16> op;  // Opcode
    mac_address_t srcHwAddr; // Sender Hardware Address
    ipv4_address_t srcIpAddr; // Sender Protocol Address
    mac_address_t targetHwAddr; // Target Hardware Address
    ipv4_address_t targetIpAddr; // Target Protocol Address
}

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
    bit<16> identifier;
    bit<16> sequence_number;
    bit<128> timestamp;
}

header icmp_options_h {
    bit<320> options;
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

header udp_application_h {
    bit<16> type;
    bit<16> session_id;
}
const bit<16> UDP_APPLICATION_H_LENGTH = 4;

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
    time_t_extended  start;
    time_t_extended  end;
    packet_count_t   packets;
    byte_count_t     bytes;
    packet_length_t  packet_length_min;
    packet_length_t  packet_length_max;
    packet_length_t  packet_length_mean;
    time_t_extended  packet_inter_arrival_time_min;
    time_t_extended  packet_inter_arrival_time_max;
    time_t_extended  packet_inter_arrival_time_mean;
}

const bit<16> FLOW_RECORD_DATA_H_LENGTH = 76;

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
    time_t_extended  forward_start;
    time_t_extended  forward_end;
    packet_count_t   forward_packets;
    byte_count_t     forward_bytes;
    packet_length_t  forward_packet_length_min;
    packet_length_t  forward_packet_length_max;
    packet_length_t  forward_packet_length_mean;
    time_t_extended  forward_packet_inter_arrival_time_min;
    time_t_extended  forward_packet_inter_arrival_time_max;
    time_t_extended  forward_packet_inter_arrival_time_mean;
    // backward flow properties
    time_t_extended  backward_start;
    time_t_extended  backward_end;
    packet_count_t   backward_packets;
    byte_count_t     backward_bytes;
    packet_length_t  backward_packet_length_min;
    packet_length_t  backward_packet_length_max;
    packet_length_t  backward_packet_length_mean;
    time_t_extended  backward_packet_inter_arrival_time_min;
    time_t_extended  backward_packet_inter_arrival_time_max;
    time_t_extended  backward_packet_inter_arrival_time_mean;
}

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
}

struct feature_metadata_t {
    bit<16> class;
    bit<16> node_id;
    bit<64> probability;
    bit<1> isTrue;
    bit<16> prevFeature;
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
struct metadata_t {
    packet_length_t packet_length;
    flow_hash_t flow_hash;
    bit<8>      flow_type;
    bit<8>      flow_export_reason;
    parser_metadata_t  parser_meta;
    ingress_metadata_t ingress_meta;
    egress_metadata_t  egress_meta;
    tenant_metadata_t tenant_meta;
    l4_metadata_t l4_meta;
    feature_metadata_t feature_meta;
}

struct headers_t {
    ethernet_h     ethernet;
    arp_h          arp;
    ipv4_h         ipv4;
    ipv4_options_h ipv4_options;
    icmp_h         icmp;
    icmp_options_h icmp_options;
    tcp_h          tcp;
    tcp_options_h  tcp_options;
    udp_h          udp;
    pm_h           pm;
    vxlan_h        vxlan;
    ethernet_h     inner_ethernet;
    arp_h          inner_arp;
    ipv4_h         inner_ipv4;
    ipv4_options_h inner_ipv4_options;
    icmp_h         inner_icmp;
    icmp_options_h inner_icmp_options;
    tcp_h          inner_tcp;
    tcp_options_h  inner_tcp_options;
    udp_h          inner_udp;
    udp_application_h udp_application;
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
