from dataclasses import dataclass
from typing import ClassVar

from file_media_stream_service.domain.enums import StreamProtocol


@dataclass(frozen=True, slots=True)
class ProtocolRoute:
    input_protocol: str
    output_protocol: str


class ProtocolAdapter:
    _routes: ClassVar[dict[StreamProtocol, ProtocolRoute]] = {
        StreamProtocol.WEBRTC: ProtocolRoute("WEBRTC", "WEBRTC"),
        StreamProtocol.RTMP: ProtocolRoute("RTMP", "HLS"),
        StreamProtocol.HLS: ProtocolRoute("HLS", "HLS"),
        StreamProtocol.WS_AUDIO: ProtocolRoute("WS_AUDIO", "WS_AUDIO"),
        StreamProtocol.WS_VIDEO: ProtocolRoute("WS_VIDEO", "WS_VIDEO"),
        StreamProtocol.WEBSOCKET: ProtocolRoute("WEBSOCKET", "WEBSOCKET"),
    }

    def resolve(self, protocol: str) -> ProtocolRoute:
        return self._routes[StreamProtocol(protocol)]
