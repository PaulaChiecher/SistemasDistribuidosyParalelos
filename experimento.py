"""
Actividad 4: comparar nodos visitados y distancias mínimas en grafos de
distintos tamaños y medir tiempos.

Uso:
    python experimento.py            # experimento completo
    python experimento.py --rapido   # tamaños chicos, para probar

Genera resultados.csv y tres gráficos PNG. Semilla fija = 2026.
"""
import csv
import os
import platform
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from grafos import (bfs_concurrente, bfs_secuencial, generar_grafo,
                    iniciar_trabajador, verificar)

SEMILLA = 2026
REPETICIONES = 5          # se informa la mediana
TRABAJADORES = [1, 2, 4, 8]
TAMANIOS_COMPLETO = [(1_000, 5_000), (10_000, 50_000),
                     (50_000, 250_000), (200_000, 1_000_000)]
TAMANIOS_RAPIDO = [(1_000, 5_000), (10_000, 50_000)]


def mediana_ms(funcion, repeticiones=REPETICIONES):
    tiempos = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        funcion()
        tiempos.append((time.perf_counter() - t0) * 1000)
    return statistics.median(tiempos)


def main():
    rapido = "--rapido" in sys.argv
    tamanios = TAMANIOS_RAPIDO if rapido else TAMANIOS_COMPLETO
    filas = []

    print(f"Equipo: {platform.processor() or platform.machine()} | "
          f"núcleos lógicos: {os.cpu_count()} | Python {platform.python_version()}")
    print(f"Semilla {SEMILLA} | {REPETICIONES} repeticiones (mediana)\n")

    for n, m in tamanios:
        adj = generar_grafo(n, m, SEMILLA)
        ref = bfs_secuencial(adj, 0)
        verificar(adj, ref, 0)
        visitados = sum(1 for d in ref if d != -1)
        dist_max = max(ref)
        # nodos por nivel (forma de la frontera)
        por_nivel = [0] * (dist_max + 1)
        for d in ref:
            if d != -1:
                por_nivel[d] += 1

        t_seq = mediana_ms(lambda: bfs_secuencial(adj, 0))
        print(f"n={n:>7} m={m:>8} | visitados={visitados} | niveles={dist_max + 1} "
              f"| frontera máx={max(por_nivel)} | secuencial={t_seq:8.1f} ms")
        filas.append(dict(n=n, m=m, modo="secuencial", trabajadores=1,
                          visitados=visitados, dist_max=dist_max, tiempo_ms=round(t_seq, 2),
                          speedup=1.0, correcto=True, dup_entre_trab=0))

        for modo, Ejecutor in (("hilos", ThreadPoolExecutor),
                               ("procesos", ProcessPoolExecutor)):
            if modo == "procesos" and n < 50_000:
                continue   # arrancar procesos no compensa en grafos chicos
            for k in TRABAJADORES:
                if modo == "procesos" and k == 1:
                    continue
                with Ejecutor(max_workers=k, initializer=iniciar_trabajador,
                              initargs=(adj,)) as ex:
                    # calentamiento: crea los hilos/procesos antes de medir
                    d, est = bfs_concurrente(adj, 0, ex, k)
                    correcto = (d == ref)
                    t = mediana_ms(lambda: bfs_concurrente(adj, 0, ex, k))
                filas.append(dict(n=n, m=m, modo=modo, trabajadores=k,
                                  visitados=sum(1 for x in d if x != -1),
                                  dist_max=max(d), tiempo_ms=round(t, 2),
                                  speedup=round(t_seq / t, 3), correcto=correcto,
                                  dup_entre_trab=est["duplicados_entre_trabajadores"]))
                print(f"   {modo:<8} k={k}: {t:9.1f} ms | speedup {t_seq / t:5.2f}x | "
                      f"correcto={correcto} | candidatos repetidos={est['duplicados_entre_trabajadores']}")

    with open("resultados.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print("\nGuardado resultados.csv")

    try:
        graficar(filas)
    except ImportError:
        print("matplotlib no está instalado: se omiten los gráficos (pip install matplotlib)")


def graficar(filas):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tams = sorted({(f["n"], f["m"]) for f in filas})
    etiquetas = [f"{n:,}".replace(",", ".") for n, _ in tams]

    # 1) tiempo vs tamaño (secuencial vs hilos con el máximo de trabajadores vs procesos)
    plt.figure(figsize=(7, 4.2))
    for modo, k, estilo in (("secuencial", 1, "o-"), ("hilos", 4, "s--"), ("procesos", 4, "^:")):
        pts = [(f["n"], f["tiempo_ms"]) for f in filas
               if f["modo"] == modo and f["trabajadores"] == k]
        if pts:
            plt.plot([p[0] for p in pts], [p[1] for p in pts], estilo,
                     label=f"{modo}" + ("" if modo == "secuencial" else f" ({k} trabajadores)"))
    plt.xscale("log"); plt.yscale("log")
    plt.xlabel("Nodos del grafo (n)"); plt.ylabel("Tiempo (ms)")
    plt.title("Tiempo de BFS según tamaño del grafo"); plt.grid(True, which="both", alpha=.3)
    plt.legend(); plt.tight_layout(); plt.savefig("grafico_tiempo_vs_tamano.png", dpi=150)
    plt.close()

    # 2) speedup vs trabajadores (hilos) para cada tamaño
    plt.figure(figsize=(7, 4.2))
    for n, m in tams:
        pts = [(f["trabajadores"], f["speedup"]) for f in filas
               if f["modo"] == "hilos" and f["n"] == n]
        if pts:
            plt.plot([p[0] for p in pts], [p[1] for p in pts], "o-", label=f"n={n:,}".replace(",", "."))
    plt.axhline(1, color="gray", lw=1, ls="--")
    plt.xlabel("Trabajadores (hilos)"); plt.ylabel("Speedup respecto del BFS secuencial")
    plt.title("Speedup de la versión concurrente con hilos"); plt.grid(True, alpha=.3)
    plt.legend(); plt.tight_layout(); plt.savefig("grafico_speedup_hilos.png", dpi=150)
    plt.close()

    # 3) speedup vs trabajadores (procesos)
    pts_proc = [f for f in filas if f["modo"] == "procesos"]
    if pts_proc:
        plt.figure(figsize=(7, 4.2))
        for n, m in tams:
            pts = [(f["trabajadores"], f["speedup"]) for f in pts_proc if f["n"] == n]
            if pts:
                plt.plot([p[0] for p in pts], [p[1] for p in pts], "o-", label=f"n={n:,}".replace(",", "."))
        plt.axhline(1, color="gray", lw=1, ls="--")
        plt.xlabel("Trabajadores (procesos)"); plt.ylabel("Speedup respecto del BFS secuencial")
        plt.title("Speedup de la versión concurrente con procesos"); plt.grid(True, alpha=.3)
        plt.legend(); plt.tight_layout(); plt.savefig("grafico_speedup_procesos.png", dpi=150)
        plt.close()
    print("Guardados los gráficos PNG")


if __name__ == "__main__":      # necesario para multiprocessing en Windows
    main()
