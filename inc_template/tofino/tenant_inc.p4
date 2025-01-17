/****************************************************************************
 * Copyright 2021-present Timo Geier
 *                        (timo.geier@cs.hs-fulda.de)
 *                        Fulda University of Applied Sciences
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 ****************************************************************************/

#include <core.p4>
#include <tna.p4>

#include "include/define.p4"
#include "include/header.p4"
#include "include/parser.p4"

// OTFs Includes




/*************************************************************************
***************** I N G R E S S   P R O C E S S I N G ********************
*************************************************************************/
control TenantINCFrameworkIngress(inout headers_t hdr,
                              inout metadata_t meta,
                              in ingress_intrinsic_metadata_t ig_intr_md, 
                              in ingress_intrinsic_metadata_from_parser_t ig_prsr_md, 
                              inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md, 
                              inout ingress_intrinsic_metadata_for_tm_t ig_tm_md) {

    bit<8> ttl_dec = 0;

    action drop() {
        ig_dprsr_md.drop_ctl = 1;
    }

    action ipv4_forward(PortId_t port) {
        ttl_dec = 0;
        ig_tm_md.ucast_egress_port = port;
    }
    
    action decrement(inout bit<8> what, in bit<8> dec_amount) {
        what = what - dec_amount;
    }

    table test { 
        key = { 
            hdr.ipv4.dst_addr: exact; 
            hdr.ipv4.src_addr: exact;
        }
        actions = { 
            ipv4_forward; 
            drop; 
            NoAction; 
        }
        size = 1024; 
        default_action = NoAction(); 
    }

    apply {
        meta.packet_length = (bit<32>) (hdr.ipv4.total_length + ETHERNET_H_LENGTH);

        if (ig_intr_md.ingress_port == 44) { ig_tm_md.ucast_egress_port = 45; }
        if (ig_intr_md.ingress_port == 45) { ig_tm_md.ucast_egress_port = 44; }
        
        // if ( hdr.ethernet.ether_type != ether_types_t.IPV4) { exit; }

        // // [In-Network Tenant Controller --> OTFs]
        if (hdr.vxlan.isValid()) { 
			  
			 }



        // // [Conditional Data Export (CDE)]
        if ((bool) meta.tenant_meta.export_flag) { 
            // Export the actual data to the tenant CNF
        }
        // // [Tenant Flow Filter]
        // Here would be the implementation for a filtering mechanism for the multi-tenant environment.

        test.apply();
        /* TTL Modifications */
        if (hdr.ipv4.isValid()) {
            decrement(hdr.ipv4.ttl, 1);
        } // else if (hdr.ipv6.isValid()) {
          //  decrement(hdr.ipv6.hop_limit, ttl_dec);
        // }
    }
    
}

/*************************************************************************
***************** E G R E S S   P R O C E S S I N G **********************
*************************************************************************/
control TenantINCFrameworkEgress(inout headers_t hdr,
                             inout metadata_t meta,
                             in egress_intrinsic_metadata_t eg_intr_md,
                             in egress_intrinsic_metadata_from_parser_t eg_prsr_md,
                             inout egress_intrinsic_metadata_for_deparser_t eg_dprsr_md,
                             inout egress_intrinsic_metadata_for_output_port_t eg_oport_md) {
   
    apply {

    }
}

/*************************************************************************
************************* S W I T C H ************************************
*************************************************************************/
Pipeline(TenantINCFrameworkIngressParser(),
         TenantINCFrameworkIngress(),
         TenantINCFrameworkIngressDeparser(),
         TenantINCFrameworkEgressParser(),
         TenantINCFrameworkEgress(),
         TenantINCFrameworkEgressDeparser()) pipe;
Switch(pipe) main;