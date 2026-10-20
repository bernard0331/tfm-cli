"""Let discord-ext-voice-recv hear DAVE-encrypted voice.

Since March 2026 every Discord call is end-to-end encrypted (DAVE). discord.py 2.7 handles DAVE for
sending, but voice-recv 0.5.x still hands the encrypted frames straight to the Opus decoder, which fails
with "corrupted stream" on every packet. This applies the decryption step proposed upstream in
imayhaveborkedit/discord-ext-voice-recv#58: decrypt each frame with the DaveSession discord.py already
keeps, using the sender's user id, before decoding.

It does nothing if the installed voice-recv already decrypts DAVE (upstream merged a fix).
"""
import logging

log = logging.getLogger("tfm.voice.dave")

SILENCE = b"\x00" * 3840  # one 20 ms frame of 48 kHz stereo silence


def apply():
    import discord
    from discord.ext.voice_recv import opus as vr_opus
    from discord.ext.voice_recv import rtp as vr_rtp

    decoder_cls = vr_opus.PacketDecoder
    if getattr(decoder_cls, "_tfm_patched", False):
        return "already patched"
    if hasattr(decoder_cls, "_dave_decrypt"):
        return "built in"
    try:
        import davey
    except ImportError:
        return "davey missing (pip install 'discord.py[voice]>=2.7.1')"

    original_decode = decoder_cls._decode_packet

    def _dave_decrypt(self, packet):
        # Only real RTP packets carry media; fake (lost) and silence packets are left alone.
        if not isinstance(packet, vr_rtp.RTPPacket) or not packet.decrypted_data:
            return
        conn = getattr(self.sink.voice_client, "_connection", None)
        session = getattr(conn, "dave_session", None)
        if session is None or not session.ready or getattr(conn, "dave_protocol_version", 0) == 0:
            return
        if self._cached_id is None:
            return
        try:
            packet.decrypted_data = session.decrypt(int(self._cached_id), davey.MediaType.audio,
                                                    bytes(packet.decrypted_data))
        except Exception as e:  # passthrough (unencrypted) frames such as silence land here
            log.debug("DAVE decrypt skipped for ssrc %s: %s", self.ssrc, e)

    def _process_packet(self, packet):
        pcm = None
        member = self._get_cached_member()
        if member is None:
            self._cached_id = self.sink.voice_client._get_id_from_ssrc(self.ssrc)
            member = self._get_cached_member()
        self._dave_decrypt(packet)
        if not self.sink.wants_opus():
            packet, pcm = self._decode_packet(packet)
        data = vr_opus.VoiceData(packet, member, pcm=pcm)
        self._last_seq = packet.sequence
        self._last_ts = packet.timestamp
        return data

    def _decode_packet(self, packet):
        # A frame that still fails to decode (sender not mapped yet, key change mid-call) becomes silence
        # instead of killing the receive thread.
        try:
            return original_decode(self, packet)
        except discord.opus.OpusError as e:
            log.debug("dropping undecodable frame from ssrc %s: %s", self.ssrc, e)
            return packet, SILENCE

    decoder_cls._dave_decrypt = _dave_decrypt
    decoder_cls._process_packet = _process_packet
    decoder_cls._decode_packet = _decode_packet
    decoder_cls._tfm_patched = True
    return "patched"
