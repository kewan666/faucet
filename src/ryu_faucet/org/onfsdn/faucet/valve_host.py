# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2015 Brad Cowie, Christopher Lorier and Joe Stringer.
# Copyright (C) 2015 Research and Education Advanced Network New Zealand Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASISo
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import valve_of


class HostCacheEntry(object):

    def __init__(self, eth_src, permanent, now):
        self.eth_src = eth_src
        self.permanent = permanent
        self.cache_time = now


class ValveHostManager(object):

    def __init__(self, eth_src_table, eth_dst_table,
                 learn_timeout, host_priority, mirror_from_port,
                 valve_in_match, valve_flowmod, valve_flowdel, valve_flowdrop):
        self.eth_src_table = eth_src_table
        self.eth_dst_table = eth_dst_table
        self.learn_timeout = learn_timeout
        self.host_priority = host_priority
        self.mirror_from_port = mirror_from_port
        self.valve_in_match = valve_in_match
        self.valve_flowmod = valve_flowmod
        self.valve_flowdel = valve_flowdel
        self.valve_flowdrop = valve_flowdrop

    def build_port_out_inst(self, vlan, in_port):
        dst_act = []
        if not vlan.port_is_tagged(in_port):
            dst_act.append(valve_of.pop_vlan())
        dst_act.append(valve_of.output_port(in_port))

        if in_port in self.mirror_from_port:
            mirror_port_num = self.mirror_from_port[in_port]
            mirror_acts = [valve_of.output_port(mirror_port_num)]
            dst_act.extend(mirror_acts)

        return [valve_of.apply_actions(dst_act)]

    def delete_host_from_vlan(self, eth_src, vlan):
        ofmsgs = []
        # delete any existing ofmsgs for this vlan/mac combination on the
        # src mac table
        ofmsgs.extend(self.valve_flowdel(
            self.eth_src_table,
            self.valve_in_match(
                self.eth_src_table, vlan=vlan, eth_src=eth_src)))

        # delete any existing ofmsgs for this vlan/mac combination on the dst
        # mac table
        ofmsgs.extend(self.valve_flowdel(
            self.eth_dst_table,
            self.valve_in_match(
                self.eth_dst_table, vlan=vlan, eth_dst=eth_src)))

        return ofmsgs

    def learn_host_on_vlan_port(self, port, vlan, eth_src):
        ofmsgs = []
        in_port = port.number

        # hosts learned on this port never relearned
        if port.permanent_learn:
            learn_timeout = 0

            # antispoof this host
            ofmsgs.append(self.valve_flowdrop(
                self.eth_src_table,
                self.valve_in_match(
                    self.eth_src_table, vlan=vlan, eth_src=eth_src),
                priority=(self.host_priority - 2)))
        else:
            learn_timeout = self.learn_timeout
            ofmsgs.extend(self.delete_host_from_vlan(eth_src, vlan))

        # Update datapath to no longer send packets from this mac to controller
        # note the use of hard_timeout here and idle_timeout for the dst table
        # this is to ensure that the source rules will always be deleted before
        # any rules on the dst table. Otherwise if the dst table rule expires
        # but the src table rule is still being hit intermittantly the switch
        # will flood packets to that dst and not realise it needs to relearn
        # the rule
        # NB: Must be lower than highest priority otherwise it can match
        # flows destined to controller
        ofmsgs.append(self.valve_flowmod(
            self.eth_src_table,
            self.valve_in_match(
                self.eth_src_table, in_port=in_port,
                vlan=vlan, eth_src=eth_src),
            priority=(self.host_priority - 1),
            inst=[valve_of.goto_table(self.eth_dst_table)],
            hard_timeout=learn_timeout))

        # update datapath to output packets to this mac via the associated port
        ofmsgs.append(self.valve_flowmod(
            self.eth_dst_table,
            self.valve_in_match(
                self.eth_dst_table, vlan=vlan, eth_dst=eth_src),
            priority=self.host_priority,
            inst=self.build_port_out_inst(vlan, in_port),
            idle_timeout=learn_timeout))
        return ofmsgs
