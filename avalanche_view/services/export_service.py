from pathlib import Path

from matplotlib import animation


class ExportService:
    """PNG now; animation writers can reuse the same figure/frame controller."""

    @staticmethod
    def export_png(figure, path: str | Path, dpi: int = 300) -> Path:
        path = Path(path).with_suffix(".png")
        if not 72 <= dpi <= 1200:
            raise ValueError("Choose an export resolution from 72 to 1200 DPI")
        figure.savefig(
            path,
            dpi=dpi,
            bbox_inches="tight",
            facecolor=figure.get_facecolor(),
            metadata={"Software": "AvalancheView"},
        )
        return path

    @staticmethod
    def animation_writer(format_name: str, fps: int = 4):
        if format_name.lower() == "gif":
            return animation.PillowWriter(fps=fps)
        if format_name.lower() == "mp4":
            if not animation.writers.is_available("ffmpeg"):
                raise RuntimeError("Install ffmpeg to export MP4")
            return animation.FFMpegWriter(fps=fps)
        raise ValueError("Animation format must be GIF or MP4")
