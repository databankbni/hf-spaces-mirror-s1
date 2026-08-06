from __future__ import annotations

from datetime import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..id_generator import IDGenerator
from ..packet import InfoPacket, PacketType
from ..plugin import Plugin

if TYPE_CHECKING:
    from ..processor import Processor


logger = logging.getLogger(__name__)


class AllModelPlugin(Plugin):
    """
    Aggregate parallel tool results.

    The plugin is intended to be attached on Agent processors. It tracks CALL
    packets that share the same batch id, intercepts RESPONSE/ERROR packets, and
    emits:
    - INTERRUPT packets while a batch is still incomplete
    - one aggregated NORMAL packet when the whole batch has completed

    v2 P2+: batch-level timeout
      - If not all results arrive within the effective timeout, the batch is
        finalized with whatever results have been received. Missing calls are
        recorded as timeout errors.
      - This prevents a single stuck/slow tool from blocking the agent forever
        (or until the caller's own timeout fires).

    v2 P3+: dynamic timeout based on batch size
      - server-side tools via safe_run_async are dispatched back to the single
        main event loop, so "parallel" tool calls effectively run serially
        (SQLite write lock + single-loop concurrency). A fixed 30s timeout
        cannot cover N serial tool calls (e.g. 5 x create_task ≈ 50s).
      - effective_timeout = base_timeout + per_tool_timeout * num_tools
        - 1 tool:  30 + 15*1 = 45s
        - 5 tools: 30 + 15*5 = 105s
        - 10 tools: 30 + 15*10 = 180s
      - per_tool_timeout defaults to 15s (covers typical CRUD tool latency
        including DB session + write + commit on local SQLite).
    """

    def __init__(
        self,
        name: Optional[str] = None,
        timeout: float = 30.0,
        per_tool_timeout: float = 15.0,
    ):
        super().__init__(name)
        self.timeout = timeout
        self.per_tool_timeout = per_tool_timeout
        self._pending_calls: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, List[InfoPacket]] = {}
        self._completed_results: Dict[str, List[InfoPacket]] = {}
        self._completion_callbacks: Dict[str, Any] = {}
        self._batch_counter = 0
        self._lock = threading.RLock()
        self._timeout_thread: Optional[threading.Thread] = None
        self._timeout_thread_stop = threading.Event()

    def clone(self) -> "AllModelPlugin":
        return AllModelPlugin(
            name=self.name,
            timeout=self.timeout,
            per_tool_timeout=self.per_tool_timeout,
        )

    def _effective_timeout(self, pending: Dict[str, Any]) -> float:
        """Compute the dynamic timeout for a batch.

        Base timeout covers a single tool's worst-case latency.
        per_tool_timeout * num_tools covers the additional serial execution
        time when multiple tools share the single main event loop.
        """
        num_tools = int(pending.get("total", 0) or 0)
        return self.timeout + self.per_tool_timeout * num_tools

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        if packet.type not in (PacketType.RESPONSE, PacketType.ERROR):
            return packet

        batch_id = packet.get_metadata("batch_id")
        if not batch_id:
            return packet

        callback = None
        callback_results: List[InfoPacket] = []
        aggregated_packet: InfoPacket | None = None

        with self._lock:
            pending = self._pending_calls.get(batch_id)
            if pending is None:
                logger.warning(
                    "[AllModelPlugin] NO pending batch for batch_id=%s — RESPONSE will pass through un-aggregated. packet_id=%s",
                    batch_id, packet.id,
                )
                return packet

            # If this batch has already been finalized by the timeout thread,
            # drop the late response to avoid duplicate processing.
            if pending.get("finalized"):
                logger.debug(
                    "[AllModelPlugin] batch_id=%s already finalized, dropping late response packet_id=%s",
                    batch_id, packet.id,
                )
                return packet

            self._results.setdefault(batch_id, []).append(packet)
            pending["received"] += 1

            if pending["received"] < pending["total"]:
                return self._create_interrupt_packet(packet, batch_id, pending)

            aggregated_packet, callback_results = self._finalize_batch(packet, batch_id, pending)
            callback = self._completion_callbacks.pop(batch_id, None)

        # Run callbacks outside the lock to avoid deadlocks when callback code
        # calls back into this plugin's public methods.
        if callback is not None:
            callback(batch_id, callback_results)
        elif self._processor is not None and hasattr(self._processor, "_on_all_complete"):
            self._processor._on_all_complete(batch_id, callback_results)

        return aggregated_packet

    def post_process(self, packet: InfoPacket, output_list: list) -> tuple:
        if packet.type != PacketType.CALL:
            return packet, output_list

        batch_id = packet.get_metadata("batch_id")
        if not batch_id:
            return packet, output_list

        with self._lock:
            if batch_id not in self._pending_calls:
                self._pending_calls[batch_id] = {
                    "total": 0,
                    "received": 0,
                    "start_time": time.time(),
                    "origin_packet_id": packet.get_metadata("batch_origin_id") or packet.parent_id,
                    "origin_chain_id": packet.chain_id,
                    "calls": {},
                    "call_order": [],
                    "finalized": False,
                }
                self._results[batch_id] = []
                self._start_timeout_watcher()

            pending = self._pending_calls[batch_id]
            pending["total"] += 1

            tool_call_id = packet.get_metadata("tool_call_id")
            if tool_call_id:
                pending["calls"][tool_call_id] = {
                    "tool_name": packet.get_metadata("tool_name"),
                    "arguments": packet.content.get("arguments") if isinstance(packet.content, dict) else None,
                    "call_packet_id": packet.id,
                }
                if tool_call_id not in pending["call_order"]:
                    pending["call_order"].append(tool_call_id)

        return packet, output_list

    def _start_timeout_watcher(self) -> None:
        """Start the background thread that finalizes timed-out batches."""
        if self._timeout_thread is not None and self._timeout_thread.is_alive():
            return
        self._timeout_thread_stop.clear()
        self._timeout_thread = threading.Thread(
            target=self._timeout_watcher_loop,
            name="allmodel-timeout-watcher",
            daemon=True,
        )
        self._timeout_thread.start()

    def _stop_timeout_watcher(self) -> None:
        """Signal the timeout watcher thread to stop."""
        self._timeout_thread_stop.set()

    def _timeout_watcher_loop(self) -> None:
        """Periodically check pending batches and finalize timed-out ones."""
        while not self._timeout_thread_stop.is_set():
            self._finalize_timed_out_batches()
            # Sleep in short increments so we can be stopped promptly.
            self._timeout_thread_stop.wait(0.5)

    def _finalize_timed_out_batches(self) -> None:
        """Finalize any batches that have exceeded their effective timeout."""
        now = time.time()
        batches_to_finalize: List[tuple[str, Dict[str, Any]]] = []

        with self._lock:
            for batch_id, pending in list(self._pending_calls.items()):
                if pending.get("finalized"):
                    continue
                elapsed = now - pending.get("start_time", now)
                if elapsed >= self._effective_timeout(pending):
                    batches_to_finalize.append((batch_id, pending))

        for batch_id, pending in batches_to_finalize:
            self._finalize_batch_by_timeout(batch_id, pending)

    def _finalize_batch_by_timeout(self, batch_id: str, pending: Dict[str, Any]) -> None:
        """Finalize a batch due to timeout and feed the result back to the agent."""
        with self._lock:
            if pending.get("finalized"):
                return
            pending["finalized"] = True

            # Generate timeout-error packets for calls that never responded.
            received_ids = {
                packet.get_metadata("tool_call_id")
                for packet in self._results.get(batch_id, [])
                if packet.get_metadata("tool_call_id") is not None
            }
            for tool_call_id, call_record in pending.get("calls", {}).items():
                if tool_call_id in received_ids:
                    continue
                timeout_packet = self._create_timeout_error_packet(
                    batch_id=batch_id,
                    tool_call_id=tool_call_id,
                    call_record=call_record,
                    pending=pending,
                )
                self._results.setdefault(batch_id, []).append(timeout_packet)
                pending["received"] += 1

            # Pick any received packet as the "last" packet for chain metadata.
            results = self._results.get(batch_id, [])
            last_packet = results[-1] if results else None
            if last_packet is None:
                self._pending_calls.pop(batch_id, None)
                self._results.pop(batch_id, None)
                return

            aggregated_packet, callback_results = self._finalize_batch(
                last_packet, batch_id, pending
            )
            callback = self._completion_callbacks.pop(batch_id, None)

        if callback is not None:
            callback(batch_id, callback_results)
        elif self._processor is not None and hasattr(self._processor, "_on_all_complete"):
            self._processor._on_all_complete(batch_id, callback_results)

        # Feed the aggregated result back into the agent so it can continue.
        if aggregated_packet is not None and self._processor is not None:
            self._processor.input(aggregated_packet)

    def _create_timeout_error_packet(
        self,
        batch_id: str,
        tool_call_id: str,
        call_record: Dict[str, Any],
        pending: Dict[str, Any],
    ) -> InfoPacket:
        """Create an ERROR packet representing a tool that timed out."""
        tool_name = call_record.get("tool_name") or "unknown_tool"
        call_packet_id = call_record.get("call_packet_id")
        effective_timeout = self._effective_timeout(pending)
        return InfoPacket(
            id=IDGenerator.generate_packet_id(
                self._processor.sender_id if self._processor else "allmodel",
                PacketType.ERROR.value,
            ),
            sender_id=self._processor.sender_id if self._processor else "allmodel",
            parent_id=call_packet_id,
            chain_id=pending.get("origin_chain_id"),
            content={
                "error": (
                    f"[Tool Timeout] {tool_name} did not return within "
                    f"{effective_timeout:.1f}s (batch {batch_id}, "
                    f"total_tools={int(pending.get('total', 0) or 0)})."
                ),
            },
            type=PacketType.ERROR,
            timestamp=datetime.now(),
            _metadata={
                "batch_id": batch_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "timeout": True,
            },
        )

    def _finalize_batch(
        self,
        last_packet: InfoPacket,
        batch_id: str,
        pending: Dict[str, Any],
    ) -> tuple[InfoPacket, List[InfoPacket]]:
        raw_results = list(self._results.get(batch_id, []))
        calls = pending.get("calls", {})
        call_order = pending.get("call_order", [])
        origin_packet_id = pending.get("origin_packet_id", last_packet.parent_id)
        origin_chain_id = pending.get("origin_chain_id") or last_packet.chain_id

        ordered_results = self._order_results(raw_results, call_order)

        aggregated_results = []
        for result_packet in ordered_results:
            tool_call_id = result_packet.get_metadata("tool_call_id")
            call_record = calls.get(tool_call_id, {})
            aggregated_results.append(
                {
                    "tool_name": call_record.get("tool_name") or result_packet.get_metadata("tool_name"),
                    "arguments": call_record.get("arguments"),
                    "result": result_packet.content,
                    "status": "error" if result_packet.type == PacketType.ERROR else "success",
                    "call_packet_id": call_record.get("call_packet_id"),
                    "response_packet_id": result_packet.id,
                    "tool_call_id": tool_call_id,
                }
            )

        self._completed_results[batch_id] = ordered_results.copy()
        self._pending_calls.pop(batch_id, None)
        self._results.pop(batch_id, None)

        aggregated_packet = InfoPacket(
            id=IDGenerator.generate_packet_id(
                self._processor.sender_id if self._processor else "allmodel",
                PacketType.NORMAL.value,
            ),
            sender_id=self._processor.sender_id if self._processor else "allmodel",
            parent_id=origin_packet_id,
            chain_id=origin_chain_id,
            content={
                "mode": "all",
                "batch_id": batch_id,
                "results": aggregated_results,
            },
            type=PacketType.NORMAL,
            timestamp=datetime.now(),
            _metadata={
                "aggregate": "all",
                "batch_id": batch_id,
                "origin_packet_id": origin_packet_id,
                "call_packet_ids": [
                    item.get("call_packet_id") for item in aggregated_results if item.get("call_packet_id")
                ],
                "response_packet_ids": [item["response_packet_id"] for item in aggregated_results],
            },
        )
        return aggregated_packet, ordered_results

    def _order_results(self, results: List[InfoPacket], call_order: List[str]) -> List[InfoPacket]:
        results_by_call: Dict[str, InfoPacket] = {}
        for packet in results:
            tool_call_id = packet.get_metadata("tool_call_id")
            if tool_call_id is not None:
                results_by_call[tool_call_id] = packet

        ordered: List[InfoPacket] = []
        used_ids: set[str] = set()
        for tool_call_id in call_order:
            packet = results_by_call.get(tool_call_id)
            if packet is None:
                continue
            ordered.append(packet)
            used_ids.add(packet.id)

        for packet in results:
            if packet.id not in used_ids:
                ordered.append(packet)
                used_ids.add(packet.id)
        return ordered

    def _create_interrupt_packet(
        self,
        original_packet: InfoPacket,
        batch_id: str,
        pending: Dict[str, Any],
    ) -> InfoPacket:
        received = int(pending.get("received", 0))
        total = int(pending.get("total", 0))
        return InfoPacket(
            id=IDGenerator.generate_packet_id(
                self._processor.sender_id if self._processor else "allmodel",
                PacketType.INTERRUPT.value,
            ),
            sender_id=self._processor.sender_id if self._processor else "allmodel",
            parent_id=original_packet.id,
            chain_id=original_packet.chain_id,
            content={
                "reason": f"{self.name}: waiting for all parallel tool results",
                "batch_id": batch_id,
                "received": received,
                "total": total,
                "pending": max(total - received, 0),
            },
            type=PacketType.INTERRUPT,
            timestamp=datetime.now(),
        )

    def _on_all_complete(self, batch_id: str) -> None:
        # Backward-compatible extension hook.
        _ = batch_id

    def create_batch_id(self) -> str:
        with self._lock:
            self._batch_counter += 1
            return f"batch_{int(time.time() * 1000)}_{self._batch_counter}"

    def register_completion_callback(self, batch_id: str, callback: Any) -> None:
        with self._lock:
            self._completion_callbacks[batch_id] = callback

    def wait_for_batch(self, batch_id: str, timeout: Optional[float] = None) -> List[InfoPacket]:
        timeout_value = timeout or self.timeout
        start_time = time.time()
        while time.time() - start_time < timeout_value:
            with self._lock:
                if batch_id not in self._pending_calls:
                    return self._completed_results.get(batch_id, []).copy()
            time.sleep(0.1)
        raise TimeoutError(f"Batch {batch_id} timed out after {timeout_value} seconds")

    def get_pending_count(self, batch_id: str) -> int:
        with self._lock:
            pending = self._pending_calls.get(batch_id)
            if pending is None:
                return 0
            return int(pending["total"]) - int(pending["received"])

    def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            pending = self._pending_calls.get(batch_id)
            if pending is None:
                return None
            return {
                "total": pending["total"],
                "received": pending["received"],
                "pending": pending["total"] - pending["received"],
                "elapsed_time": time.time() - pending["start_time"],
            }

    def cancel_batch(self, batch_id: str) -> bool:
        with self._lock:
            if batch_id not in self._pending_calls:
                return False
            self._pending_calls.pop(batch_id, None)
            self._results.pop(batch_id, None)
            self._completion_callbacks.pop(batch_id, None)
            return True

    def get_all_pending_batches(self) -> List[str]:
        with self._lock:
            return list(self._pending_calls.keys())
