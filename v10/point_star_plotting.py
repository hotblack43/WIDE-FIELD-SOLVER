"""Shared plotting output helpers."""


def save_png(figure, target, **kwargs):
    """Save a figure as a lossless PNG with fast compression."""
    figure.savefig(target, pil_kwargs={'compress_level': 1}, **kwargs)
