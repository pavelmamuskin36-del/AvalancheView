from avalanche_view.data.dataset import Dataset


class WRFDataset(Dataset):
    """WRF adapter; shared implementation also supports ordinary CF NetCDF."""

    def earth_relative_wind(self, timestep: int = 0, level: int = 0, variable="Wind Speed 10m"):
        """Rotate WRF grid-relative winds if rotation coefficients are supplied."""
        names = {
            "Wind Speed 10m": ("U10", "V10"),
            "Wind Speed (UU/VV)": ("UU", "VV"),
            "Wind Speed (U/V)": ("U", "V"),
        }
        if variable not in names:
            raise ValueError("Выберите слой скорости ветра U10/V10, UU/VV или U/V")
        u_name, v_name = names[variable]
        u, v = self.read(u_name, timestep, level), self.read(v_name, timestep, level)
        if {"COSALPHA", "SINALPHA"} <= self.variables.keys():
            cosine = self.read("COSALPHA", timestep)
            sine = self.read("SINALPHA", timestep)
            return u * cosine - v * sine, v * cosine + u * sine
        if self.projection is not None and self.metadata.get("MAP_PROJ") != 6:
            raise ValueError(
                "Wind vectors need COSALPHA/SINALPHA for this WRF projection. "
                "Use Wind Speed 10m to display the rotation-invariant speed."
            )
        return u, v
