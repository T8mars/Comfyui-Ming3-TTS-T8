import torch
from ming_t8.kda import recurrent_kda, ShortConvolution
from ming_t8.quantization import regular_hadamard, rotate, dequantize


def test_kda_chunk_boundaries_preserve_full_sequence_state():
    generator = torch.Generator().manual_seed(21)
    q, k, v, g = [torch.randn(1, 9, 2, 4, generator=generator) for _ in range(4)]
    beta = torch.rand(1, 9, 2, generator=generator)
    parameters = {"A_log": torch.zeros(2), "dt_bias": torch.zeros(8), "lower_bound": -5.0}
    whole, state = recurrent_kda(q, k, v, g, beta, **parameters)
    first, state_first = recurrent_kda(q[:, :4], k[:, :4], v[:, :4], g[:, :4], beta[:, :4], **parameters)
    second, state_second = recurrent_kda(q[:, 4:], k[:, 4:], v[:, 4:], g[:, 4:], beta[:, 4:], initial_state=state_first, **parameters)
    torch.testing.assert_close(whole, torch.cat([first, second], 1))
    torch.testing.assert_close(state, state_second)


def test_short_convolution_streaming_retains_causal_history():
    conv = ShortConvolution(3, 4)
    torch.nn.init.normal_(conv.weight)
    x = torch.randn(1, 11, 3)
    whole, _ = conv(x)
    cache, chunks = None, []
    for start, end in [(0, 1), (1, 5), (5, 6), (6, 11)]:
        output, cache = conv(x[:, start:end], cache, output_final_state=True)
        chunks.append(output)
    torch.testing.assert_close(whole, torch.cat(chunks, 1))


def test_regular_rotation_is_involutory_and_preserves_linear_output():
    h = regular_hadamard(256)
    torch.testing.assert_close(h @ h.T, torch.eye(256))
    x, w = torch.randn(2, 512), torch.randn(7, 512)
    torch.testing.assert_close(x @ w.T, rotate(x) @ rotate(w).T, rtol=2e-5, atol=2e-5)
    quant = torch.randint(-127, 128, (7, 512), dtype=torch.int8)
    scale = torch.rand(7, 1) * .01
    recovered = dequantize(quant, scale, convrot=True, dtype=torch.float32)
    torch.testing.assert_close(rotate(recovered), quant.float() * scale, rtol=2e-5, atol=2e-5)
