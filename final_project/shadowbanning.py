import time
import copy
import random
import pickle
from dataclasses import dataclass
from typing import Tuple, Mapping, Set, Iterable, Optional, List, Any

import matplotlib.pyplot as plt
import numpy as np
import networkx as nx
import zmq

AgentID = int
AgentSet = Set[AgentID]

Phi = np.ndarray
TrustedSet = Set[AgentID]


@dataclass
class MsgContents:
    id: AgentID
    phi: np.ndarray
    no_longer_trusted_set: Set[AgentID]


ZMQ_ADDR = "ipc:///tmp/rc_demo"
ZMQ_TIMEOUT_MS = 100
ONE_HOP_TOPIC = "one_hop"
TWO_HOP_TOPIC = "two_hop"

BAD_NODE_ITERATION = 3

random.seed(1234)
TWO_HOP_PROBABILITY = 0.5

VANILLA_FILE_NAME = "vanilla.pkl"
ERROR_FILE_NAME = "introduced_error.pkl"


class ZMQWrapper:
    def __init__(
        self, id: AgentID, graph: nx.DiGraph, two_hop_probability: float
    ) -> None:
        self.id = id
        self.in_neighbors = set(graph.predecessors(id))

        # Comms doesn't track graph structure, just topics and such
        self.two_hop_in_neighbors = set()
        for n in self.in_neighbors:
            two_hop_neighbors = set(graph.predecessors(n))
            self.two_hop_in_neighbors.update(two_hop_neighbors)

        self.ctx = zmq.Context()
        self.pub_addr = f"{ZMQ_ADDR}_{id}"

        self.pub_sock = self.ctx.socket(zmq.PUB)
        self.pub_sock.bind(self.pub_addr)

        self.sub_socks = []
        all_neighbors = set()
        all_neighbors.update(self.in_neighbors)
        all_neighbors.update(self.two_hop_in_neighbors)
        for n in all_neighbors:
            assert isinstance(n, AgentID)

        for n in all_neighbors:
            sock = self.ctx.socket(zmq.SUB)
            to_connect = f"{ZMQ_ADDR}_{n}"
            sock.connect(to_connect)
            if n in self.in_neighbors:
                sock.setsockopt_string(zmq.SUBSCRIBE, ONE_HOP_TOPIC)
                sock.setsockopt(zmq.RCVTIMEO, ZMQ_TIMEOUT_MS)
            if n in self.two_hop_in_neighbors:
                sock.setsockopt_string(zmq.SUBSCRIBE, TWO_HOP_TOPIC)
                sock.setsockopt(zmq.RCVTIMEO, ZMQ_TIMEOUT_MS)

            self.sub_socks.append((n, sock))

        assert len(self.sub_socks) == len(all_neighbors)

        assert 0.0 < two_hop_probability < 1.0
        self.two_hop_probability = two_hop_probability

    def publish(self, data: Tuple[AgentID, np.ndarray, np.ndarray]):
        msg = bytes(pickle.dumps(data))
        self.pub_sock.send_multipart([bytes(ONE_HOP_TOPIC, encoding="UTF-8"), msg])
        if random.random() < self.two_hop_probability:
            self.pub_sock.send_multipart([bytes(TWO_HOP_TOPIC, encoding="UTF-8"), msg])

    def receive(self) -> Mapping[AgentID, Tuple[np.ndarray, np.ndarray]]:
        ret = dict()
        for n, sock in self.sub_socks:
            do_read = True
            while do_read:
                try:
                    topic, msg = sock.recv_multipart()
                    sender, sigma, eta = pickle.loads(msg)
                    if sender in ret:
                        # TODO: Handle dupe transmissions here, may just be a
                        # one/two hop case
                        pass
                    ret[sender] = (sigma, eta)
                except zmq.error.Again:
                    do_read = False

        return ret


class ShadowBanningZMQ:
    def __init__(
        self, id: AgentID, graph: nx.DiGraph, two_hop_probability: float
    ) -> None:
        self.id = id
        self.in_neighbors = set(graph.predecessors(id))

        # Comms doesn't track graph structure, just topics and such
        self.two_hop_in_neighbors = set()
        for n in self.in_neighbors:
            two_hop_neighbors = set(graph.predecessors(n))
            self.two_hop_in_neighbors.update(two_hop_neighbors)

        self.ctx = zmq.Context()
        self.pub_addr = f"{ZMQ_ADDR}_{id}"

        self.pub_sock = self.ctx.socket(zmq.PUB)
        self.pub_sock.bind(self.pub_addr)

        self.sub_socks = []
        all_neighbors = set()
        all_neighbors.update(self.in_neighbors)
        all_neighbors.update(self.two_hop_in_neighbors)
        for n in all_neighbors:
            assert isinstance(n, AgentID)

        for n in all_neighbors:
            sock = self.ctx.socket(zmq.SUB)
            to_connect = f"{ZMQ_ADDR}_{n}"
            sock.connect(to_connect)
            if n in self.in_neighbors:
                sock.setsockopt_string(zmq.SUBSCRIBE, ONE_HOP_TOPIC)
                sock.setsockopt(zmq.RCVTIMEO, ZMQ_TIMEOUT_MS)
            if n in self.two_hop_in_neighbors:
                sock.setsockopt_string(zmq.SUBSCRIBE, TWO_HOP_TOPIC)
                sock.setsockopt(zmq.RCVTIMEO, ZMQ_TIMEOUT_MS)

            self.sub_socks.append((n, sock))

        assert len(self.sub_socks) == len(all_neighbors)

        assert 0.0 < two_hop_probability < 1.0
        self.two_hop_probability = two_hop_probability

    def recv(self) -> Mapping[AgentID, Optional[MsgContents]]:
        ret = dict()
        for n, sock in self.sub_socks:
            do_read = True
            while do_read:
                try:
                    topic, msg = sock.recv_multipart()
                    msg_contents: MsgContents = pickle.loads(msg)
                    if msg_contents.id in ret:
                        # TODO: Handle dupe transmissions here, may just be a
                        # one/two hop case
                        pass
                    ret[msg_contents.id] = msg_contents
                except zmq.error.Again:
                    do_read = False

        if self.id not in ret:
            print("Self loop failed, something is janky!")

        return ret

    def publish(self, data: MsgContents) -> None:
        msg = bytes(pickle.dumps(data))
        self.pub_sock.send_multipart([bytes(ONE_HOP_TOPIC, encoding="UTF-8"), msg])
        if random.random() < self.two_hop_probability:
            self.pub_sock.send_multipart([bytes(TWO_HOP_TOPIC, encoding="UTF-8"), msg])


class RCVariables:
    def __init__(
        self,
        id: AgentID,
        in_neighbors: AgentSet,
        out_neighbors: AgentSet,
        y: np.ndarray,
        z: np.ndarray,
    ) -> None:
        self.id = id
        self.in_neighbors = in_neighbors
        self.in_neighbors.add(id)
        self.out_neighbors = out_neighbors
        self.out_neighbors.add(id)

        self.out_degree = len(self.out_neighbors)

        self.y = self.sigma = self.rho = self.z = self.eta = self.nu = (
            self.broadcasted
        ) = None
        self.reset(y, z)

    def ratio(self) -> np.ndarray:
        r = self.y / self.z
        assert np.all(np.isfinite(r))

        return r

    def reset(self, y: np.ndarray, z: np.ndarray) -> None:
        self.y = y
        self.sigma = np.zeros_like(y)
        self.rho = {n: [np.zeros_like(y), np.zeros_like(y)] for n in self.in_neighbors}
        self.z = z
        self.eta = np.zeros_like(z)
        self.nu = {n: [np.zeros_like(z), np.zeros_like(z)] for n in self.in_neighbors}
        self.broadcasted = False

    def broadcast(self) -> Tuple[AgentID, np.ndarray, np.ndarray]:
        assert not self.broadcasted

        self.sigma += self.y / self.out_degree
        self.eta += self.z / self.out_degree
        self.broadcasted = True

        return (self.id, self.sigma, self.eta)

    def update_y_z(
        self, rcvd_sigma_eta: Mapping[AgentID, Tuple[np.ndarray, np.ndarray]]
    ) -> None:
        # TODO more error checking, this is too trusting
        assert self.broadcasted
        assert len(rcvd_sigma_eta) > 0

        for id, (sigma, eta) in rcvd_sigma_eta.items():
            self.rho[id][1] = self.rho[id][0]
            self.rho[id][0] = sigma

            self.nu[id][1] = self.nu[id][0]
            self.nu[id][0] = eta

        # There's a better way to do this with numpy but w/e
        new_y = np.zeros_like(self.y)
        new_z = np.zeros_like(self.z)
        for id, pair in self.rho.items():
            new_y += pair[0] - pair[1]
        for id, pair in self.nu.items():
            new_z += pair[0] - pair[1]

        assert np.all(np.isfinite(new_y))
        assert np.all(np.isfinite(new_z))

        self.y = new_y
        self.z = new_z
        self.broadcasted = False


class VanillaRC:
    """
    Lifted and adapted from existing C++ work to verify operation in Python
    """

    def __init__(
        self,
        y: np.ndarray,
        z: np.ndarray,
        id: AgentID,
        graph: nx.DiGraph,
        two_hop_tx_chance: float,
    ) -> None:
        self.id = id
        self.graph = graph
        if not self.graph.has_node(self.id):
            raise ValueError(f"Graph doesn't contain the requested node ID: {self.id}")

        self.i_neighbors = set(graph.predecessors(id))
        self.o_neighbors = set(graph.successors(id))

        assert len(self.i_neighbors) > 1
        assert len(self.o_neighbors) > 1

        self.out_degree = len(self.o_neighbors)

        self.rcvars = RCVariables(self.id, self.i_neighbors, self.o_neighbors, y, z)

        self.socket = ZMQWrapper(id, graph, two_hop_tx_chance)

    def broadcast(self) -> None:
        bcast = self.rcvars.broadcast()
        # TODO send the broadcast!
        self.socket.publish(bcast)
        self.broadcasted = True

    def receive_and_update(self) -> None:
        # TODO update this to reflect the new Msg class
        rcvd = self.socket.receive()
        i_neighbor_updates = self._filter_rcvd(rcvd)
        self.rcvars.update_y_z(i_neighbor_updates)

    def ratio(self) -> np.ndarray:
        return self.rcvars.ratio()

    def reset(self, y: np.ndarray, z: np.ndarray) -> None:
        self.rcvars.reset(y, z)

    def _filter_rcvd(
        self, rcvd_sigma_eta: Mapping[AgentID, Tuple[np.ndarray, np.ndarray]]
    ) -> Mapping[AgentID, Tuple[np.ndarray, np.ndarray]]:
        ret = dict()
        for key, val in rcvd_sigma_eta.items():
            if key in self.i_neighbors:
                ret[key] = val

        return ret


def _get_mapping_of_optional(
    ids: Iterable[AgentID], default_init=None
) -> Mapping[AgentID, Optional[Any]]:
    return {i: default_init for i in ids}


class ShadowBanningRC:
    """
    This algorithm appears different enough that I want a full rewrite mimicking
    the paper as closely as possible. Then, I'll eventually go back and get
    smarter about the structures and naming and such.
    """

    def __init__(self, id: AgentID, graph: nx.DiGraph, x: np.ndarray) -> None:
        self.id = AgentID(id)
        self.graph = graph
        self.comms = ShadowBanningZMQ(self.id, self.graph, TWO_HOP_PROBABILITY)

        # Construct the prototypical values for x
        self.x: List[Mapping[AgentID, Optional[np.ndarray]]] = [
            _get_mapping_of_optional(set(self.graph.predecessors(self.id)))
        ]
        # TODO check that x is 2d
        self.x[0][self.id] = x

        self.phi: List[Mapping[AgentID, Optional[np.ndarray]]] = [
            _get_mapping_of_optional(
                set(self.graph.predecessors(self.id)), np.zeros_like(x)
            )
        ]

        self.psi: List[Mapping[AgentID, np.ndarray]] = [
            _get_mapping_of_optional(
                (self.graph.predecessors(self.id)), np.zeros_like(x)
            )
        ]
        one_and_two_hop = set()
        two_hop = [
            set(self.graph.predecessors(n))
            for n in set(self.graph.predecessors(self.id))
        ]

        one_and_two_hop.update(set(self.graph.predecessors(self.id)))
        for subset in two_hop:
            one_and_two_hop.update(subset)
        self.M = one_and_two_hop
        self.mu = [
            {
                AgentID(i): {
                    l: np.zeros_like(x) for l in set(self.graph.predecessors(i))
                }
                for i in set(self.graph.predecessors(self.id))
            }
        ]

        # TODO inner data structure may need to be a map of sets
        in_neighbors = set(self.graph.predecessors(self.id))
        two_hop_neighbors = set()
        for i in in_neighbors:
            two_hop_neighbors.update(set(self.graph.predecessors(i)))

        self.trusted: List[Set[AgentID]] = [set(self.M)]
        self.not_trusted = [set()]

        # This starts empty and is populated later
        # The agent ids are the ones in our two-hop neighborhood
        self.zeta: List[Mapping[AgentID, bool]] = []

        # The invariant quantity of interest
        self.gamma: List[Mapping[AgentID, Optional[np.ndarray]]] = []

        self.k = 0

    def rcv(self) -> Mapping[AgentID, Optional[MsgContents]]:
        """Returns the transmissions from each agent, which include the value of
        phi and the untrusted nodes"""
        ret = {n: None for n in self.M}
        rcvd = self.comms.recv()
        assert set(rcvd.keys()).issubset(
            ret.keys()
        ), f"Received packets from outside M.\nM:{ret.keys()}\nrcvd: {rcvd.keys()}"

        for n in rcvd:
            ret[n] = rcvd[n]

        return ret

    def t2_and_t3(self) -> None:
        print(f"Now on interation {self.k}")
        new_local_phi = self.phi[self.k][self.id] + (
            self.x[self.k][self.id] / self.graph.out_degree(self.id)
        )
        tmp = {i: None for i in self.phi[self.k]}
        tmp[self.id] = new_local_phi

        to_send = MsgContents(self.id, new_local_phi, self.not_trusted[self.k])
        self.comms.publish(to_send)

    def t4_through_t8(self) -> None:
        # t4, receive the messages
        msgs = self.rcv()
        new_trusted = copy.copy(self.trusted[self.k])
        new_untrusted = copy.copy(self.not_trusted[self.k])

        # Update zetas
        new_zeta = _get_mapping_of_optional(self.M, False)
        # t5, Update local copies of Ti[k] and zetas
        for n, msg in msgs.items():
            if msg is None:
                continue
            new_trusted = new_trusted - msg.no_longer_trusted_set
            new_untrusted = new_untrusted | msg.no_longer_trusted_set
            new_zeta[n] = True

        self.trusted.append(new_trusted)
        self.not_trusted.append(new_untrusted)
        self.zeta.append(new_zeta)

        ## T6
        # Update phi's and psi's
        new_phis = _get_mapping_of_optional(set(self.graph.predecessors(self.id)))
        new_psis: Mapping[AgentID, np.ndarray] = _get_mapping_of_optional(
            set(self.graph.predecessors(self.id)), np.zeros_like(self.x[0][self.id])
        )
        assert new_psis.keys() == new_phis.keys()
        assert self.id in new_phis

        for n, msg in msgs.items():
            if msg is None:
                new_phis[n] = None
            else:
                new_phis[n] = msg.phi
            if n in self.trusted[self.k] and msg is not None:
                new_psis[n] = msg.phi
            else:
                # Needn't do anything, these default to 0's
                pass

        # This is wrong, there is already a phi for the current iteration. We need to update it, not append
        self.phi.append(new_phis)
        self.psi.append(new_psis)

        # update mu's
        new_mu = {}
        for i in set(self.graph.predecessors(self.id)):
            new_mu[i] = _get_mapping_of_optional(set(self.graph.predecessors(i)))
            for l in set(self.graph.predecessors(i)):
                assert (
                    l in self.zeta[self.k]
                ), f"Agent {self.id}: Two hop neighbor {l}, in neighbor of {i}, not in zeta: {self.zeta[self.k]}"
                if self.zeta[self.k][l] and l in self.trusted[self.k]:
                    if msgs[l] is None:
                        UserWarning(
                            f"Zeta for {l} was True but no message from it is in msgs"
                        )
                        continue
                    phi_l = msgs[l].phi
                    new_mu[i][l] = phi_l
                elif (not self.zeta[self.k][l]) and l in self.trusted[self.k]:
                    new_mu[i][l] = copy.copy(self.mu[self.k][i][l])
                else:
                    new_mu[i][l] = np.zeros_like(self.x[0][self.id])

        self.mu.append(new_mu)

        ## T6.5
        # Not explicitly listed, but let's go ahead and calculate all the remote
        # x's we can for use in calculation of gamma
        for i in self.x[self.k]:
            if i == self.id:
                # We should already know our own x[k] :)
                assert self.x[self.k][i] is not None
                continue

            xik = None
            if self.phi[self.k + 1][i] is not None and self.phi[self.k][i] is not None:
                xik = (
                    self.phi[self.k + 1][i] - self.phi[self.k][i]
                ) * self.graph.out_degree(i)
            self.x[self.k][i] = xik

        ## T7
        # Calculate the invariant gamma
        new_gamma: Mapping[AgentID, Optional[np.ndarray]] = {
            i: None for i in set(self.graph.predecessors(self.id))
        }
        # We can't make any assesments at the first (0-th?) iteration
        if self.k > 0:
            for i in self.graph.predecessors(self.id):
                # Heard from all of i's in-neighbors?
                zeta_il = {l: False for l in set(self.graph.predecessors(i))}
                for l in zeta_il:
                    zeta_il[l] = self.zeta[self.k - 1][l]

                heard_from_all = all([val for _, val in zeta_il.items()])

                i_trusted = self.trusted[self.k]
                all_trusted = set(self.graph.predecessors(i)) <= i_trusted

                if heard_from_all and all_trusted:
                    out_deg_i = self.graph.out_degree(i)
                    mu_sum = np.zeros_like(self.x[self.k][self.id])
                    for l in set(self.graph.predecessors(i)):
                        mu_sum += self.mu[self.k][i][l]
                    gamma_i = (
                        out_deg_i * (self.phi[self.k + 1][i] - self.phi[1][i])
                        - self.phi[self.k][i]
                        - mu_sum
                    )
                    new_gamma[i] = gamma_i
        self.gamma.append(new_gamma)

        # Update our trust set
        new_trusted = copy.copy(self.trusted[self.k + 1])
        new_untrusted = copy.copy(self.not_trusted[self.k + 1])
        for n, gamma_ in self.gamma[self.k].items():
            if gamma_ is None:
                continue
            if not np.allclose(np.zeros_like(gamma_), gamma_):
                # Not trusted!
                print(
                    f"Agent {self.id}: Invariant for node {n} changed, "
                    f"gamma={gamma_} =/= 0. Removing from the trusted set..."
                )
                if n not in new_trusted:
                    print(f"Agent {self.id} already didn't trust {n}")
                new_trusted.discard(n)
                new_untrusted.add(n)
                print(f"Agent {self.id} Trusted nodes: {new_trusted}")
                print(f"Agent {self.id} Untrusted nodes: {new_untrusted}")
        self.trusted[self.k + 1] = new_trusted
        self.not_trusted[self.k + 1] = new_untrusted

        ## T8
        # Finally, calculate our new x
        xjk = copy.copy(self.x[self.k][self.id])
        psi_sum = np.zeros_like(xjk)
        for i in set(self.graph.predecessors(self.id)):
            psi_sum += self.psi[self.k + 1][i] - self.psi[self.k][i]

        mu_sum = np.zeros_like(xjk)

        for i in set(self.graph.predecessors(self.id)) - self.trusted[self.k + 1]:
            for l in set(self.graph.predecessors(i)):
                mu_sum += (
                    self.mu[self.k + 1][i][l] - self.mu[self.k + 1][i][l]
                ) / self.graph.out_degree(i)

        new_xj = xjk / self.graph.out_degree(self.id) + psi_sum + mu_sum
        new_x = copy.copy(self.x[self.k])
        new_x[self.id] = new_xj
        self.x.append(new_x)

        # Increase our iteration count!
        self.k += 1

    def broadcast(self) -> None:
        self.t2_and_t3()

    def receive_and_update(self) -> None:
        self.t4_through_t8()

    def introduce_error(self, epsilon: np.ndarray) -> None:
        """
        Intentionally adds the error epsilon into our current num/den
        """
        assert (
            self.x[self.k][self.id].shape == epsilon.shape
        ), f"x shape: {self.x[self.k][self.id].shape}; eps shape: {epsilon.shape}"
        self.x[self.k][self.id] += epsilon

    def lie_about_loss_of_trust(self, id: AgentID) -> None:
        """
        She's a witch! Or maybe not. Anyway, arbitrarily declare an adjacent
        node as untrustworthy and try to banish them!
        """
        assert id in self.trusted[self.k]
        assert id not in self.not_trusted[self.k]

        self.not_trusted[self.k].add(id)
        self.trusted[self.k].remove(id)

    def ratio(self) -> np.ndarray:
        return self.x[self.k][self.id][0] / self.x[self.k][self.id][1]


def get_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from([1, 2, 3, 4, 5])
    graph.add_edges_from(
        [
            (1, 1),
            (1, 2),
            (1, 5),
            (2, 2),
            (2, 3),
            (2, 5),
            (3, 3),
            (3, 2),
            (3, 4),
            (4, 4),
            (4, 5),
            (4, 1),
            (5, 5),
            (5, 3),
            (5, 4),
        ]
    )

    assert nx.is_strongly_connected(graph)

    return graph


def main_shadowban_nominal() -> None:
    graph = get_graph()
    nodes = sorted([i for i in graph.nodes])
    # Just doing an averaging problem
    ys = [np.ones((1,)) * i for i in nodes]
    zs = [np.ones((1,)) for _ in nodes]
    agents = [
        ShadowBanningRC(i, graph, np.array([ys[i - 1], zs[i - 1]])) for i in nodes
    ]

    expected_avg = sum(nodes) / len(nodes)
    print(f"Expected average: {expected_avg}")

    time.sleep(1.0)

    while True:
        print("=" * 80)
        for agent in agents:
            agent.broadcast()
        for agent in agents:
            agent.receive_and_update()

        done = True
        print("=" * 80)
        for agent in agents:
            print(f"{agent.id} ratio: {agent.ratio()}")
            if not np.allclose(agent.ratio(), expected_avg):
                done = False

        if done:
            print("Converged!")
            break

    for agent in agents:
        agent.comms = None  # Not pickleable
    with open(VANILLA_FILE_NAME, "wb") as f:
        pickle.dump(agents, f, protocol=pickle.HIGHEST_PROTOCOL)


def main_shadowban_introduce_error() -> None:
    graph = get_graph()
    nodes = sorted([i for i in graph.nodes])
    # Just doing an averaging problem
    ys = [np.ones((1,)) * i for i in nodes]
    zs = [np.ones((1,)) for i in nodes]
    agents: List[ShadowBanningRC] = [
        ShadowBanningRC(i, graph, np.array([ys[i - 1], zs[i - 1]])) for i in nodes
    ]

    array_shape = np.array([ys[0], zs[0]]).shape

    expected_avg = sum(nodes) / len(nodes)
    print(f"Expected average: {expected_avg}")

    time.sleep(1.0)

    for i in range(20):
        if i == BAD_NODE_ITERATION:
            print("Introducing error into agent 3")
            # Let's make the error egregious for near certain detection
            error = np.array([1.0, 2.0]) * 1000.0
            error = error.reshape(array_shape)
            agents[2].introduce_error(error)

        for agent in agents:
            agent.broadcast()
        for agent in agents:
            agent.receive_and_update()

        done = True
        for agent in agents:
            print("=" * 80)
            print(f"{agent.id} ratio: {agent.ratio()}")
            print("=" * 80)
            if not np.allclose(agent.ratio(), expected_avg):
                done = False

        if done:
            print("Converged!")
            break

    for agent in agents:
        agent.comms = None  # Not pickleable
    with open(ERROR_FILE_NAME, "wb") as f:
        pickle.dump(agents, f, protocol=pickle.HIGHEST_PROTOCOL)


if __name__ == "__main__":
    main_shadowban_nominal()
    main_shadowban_introduce_error()
