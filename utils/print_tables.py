__all__ = ["print_rich_table"]


import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table


# --------------------------------------------------
def print_rich_table(df: pd.DataFrame, title: str = "Reporte"):
    console = Console()
    table = Table(
        title=title, show_header=True, header_style="bold magenta", border_style="blue"
    )

    # Añadir columnas
    for column in df.columns:
        # Alineamos a la derecha si son números
        justify = "right" if df[column].dtype in [np.float64, np.int64] else "left"
        table.add_column(column, justify=justify)

    # Añadir filas (limitamos a las primeras 20 para no inundar la terminal)
    rows_to_show = df.head(20)
    for _, row in rows_to_show.iterrows():
        formatted_row = []
        for val in row:
            # Formatear números con separador de miles y 2 decimales
            if isinstance(val, (float, np.float64)):
                formatted_row.append(f"{val:,.2f}")
            else:
                formatted_row.append(str(val))
        table.add_row(*formatted_row)

    console.print(table)
    if len(df) > 20:
        console.print(
            f"[italic yellow]... mostrando solo las primeras 20 filas de {len(df)} totales.[/italic yellow]"
        )
