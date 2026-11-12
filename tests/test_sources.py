import json

from communicaid.sources import frame_from_packet


def test_contract_v1_frame():
    msg = json.loads('{"type":"frame","seq":1,"t":3.5,"dir":[0.1,-0.2,0.97],"blinkL":0.1,"blinkR":0.2,'
                     '"browIn":0.3,"browOutL":0.4,"browOutR":0.5,"tracked":true,"dist":0.45}')
    f = frame_from_packet(msg)
    assert f.dir == (0.1, -0.2, 0.97) and f.tracked and f.dist == 0.45
    assert (f.brow_in, f.brow_out_l, f.brow_out_r) == (0.3, 0.4, 0.5)


def test_head_direction_is_read():
    f = frame_from_packet({"type": "frame", "t": 1.0, "dir": [0, 0, 1], "eye": [0, 0, -0.5], "head": [0.1, 0.2, 0.97]})
    assert f.head == (0.1, 0.2, 0.97)
    assert frame_from_packet({"type": "frame", "t": 1.0, "dir": [0, 0, 1]}).head is None


def test_face_lost_frame_has_no_direction():
    # Swift leaves out nil optionals, so "dir" is simply missing.
    f = frame_from_packet({"type": "frame", "seq": 2, "t": 4.0, "blinkL": 0, "blinkR": 0, "tracked": False, "dist": 0})
    assert f.dir is None and not f.tracked


def test_older_phone_build_still_works():
    f = frame_from_packet({"seq": 3, "t": 1.0, "eye": [0, 0, -0.4], "dir": [0, 0, 1], "dirEye": [0, 0, 1],
                           "blinkL": 0.05, "blinkR": 0.04})
    assert f.tracked and f.brow_in == 0.0


def test_phone_link_is_reported(world):
    from communicaid.sources import ArkitSource
    from conftest import run
    bus, clock, rec = world
    src = ArkitSource(bus, clock, 0)
    src.datagram_received(b'{"type":"frame","t":1,"dir":[0,0,1],"tracked":true}', ("10.7.34.50", 5555))
    assert rec.of("link")[-1] == {"phone": True, "address": "10.7.34.50"}
    run(bus, clock, 2.5)                      # the phone stops sending
    assert rec.of("link")[-1]["phone"] is False
