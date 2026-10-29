import numpy as np
import pytest
import soundfile as sf
import torch


def test_reference_crop_uses_selected_pcm_and_preserves_manual_transcript(tmp_path,monkeypatch):
    monkeypatch.setenv("MING_T8_DATA",str(tmp_path))
    from nodes import MingT8Reference
    samples=torch.stack((torch.linspace(-.1,.2,16000),torch.linspace(.3,-.1,16000))).unsqueeze(0)
    source={"waveform":samples,"sample_rate":16000}
    node=MingT8Reference()
    selected,text=node.prepare(source,"裁切后对应文字",start_seconds=.2,end_seconds=.8)
    actual,rate=sf.read(selected["path"],dtype="float32",always_2d=True)
    assert rate==16000 and np.array_equal(actual,samples[0,:,3200:12800].T.numpy())
    assert text==selected["text"]=="裁切后对应文字"
    assert selected["crop"]=={"start":.2,"end":.8}
    same,_=node.prepare({"waveform":samples[...,3200:12800],"sample_rate":16000},text)
    assert same["path"]==selected["path"]
    for start,end in ((.8,.2),(0,1.5),(float("nan"),0),(-.1,0)):
        with pytest.raises(ValueError):node.prepare(source,start_seconds=start,end_seconds=end)
