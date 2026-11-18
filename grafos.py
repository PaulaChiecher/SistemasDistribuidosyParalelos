"""
TP - Algoritmos concurrentes sobre grafos (Sistemas Distribuidos y Paralelos)

Contenido
  1. Representación del grafo (lista de adyacencia) y BFS secuencial.
  2. BFS concurrente por niveles: la frontera se reparte entre trabajadores.
  3. Reunión y eliminación de duplicados antes de avanzar de nivel.
  4. Verificación de corrección (distancias mínimas en cantidad de aristas).

Ejecutar `python grafos.py` corre un ejemplo pequeño con traza paso a paso,
una demostración de la condición de carrera y las pruebas de corrección.
"""
import random
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 1. REPRESENTACIÓN DEL GRAFO
# ---------------------------------------------------------------------------
# Grafo no dirigido y sin pesos. Lista de adyacencia: adj[u] = [vecinos de u].
# Memoria O(n + m) y recorrer los vecinos de u cuesta O(grado(u)).


def crear_grafo(n, aristas):
    """Construye la lista de adyacencia a partir de una lista de aristas."""
    adj = [[] for _ in range(n)]
    for u, v in aristas:
        adj[u].append(v)
        adj[v].append(u)
    return adj


def generar_grafo(n, m, semilla=2026):
    """
    Grafo aleatorio conexo con n nodos y m aristas (m >= n - 1).
    Primero un árbol aleatorio (garantiza conectividad) y luego aristas
    extra al azar sin repetir. La semilla hace el experimento reproducible.
    """
    rng = random.Random(semilla)
    adj = [[] for _ in range(n)]
    usadas = set()
    for v in range(1, n):
        u = rng.randrange(v)
        adj[u].append(v)
        adj[v].append(u)
        usadas.add(u * n + v)
    faltan = m - (n - 1)
    while faltan > 0:
        u, v = rng.randrange(n), rng.randrange(n)
        if u == v:
            continue
        if u > v:
            u, v = v, u
        clave = u * n + v
        if clave in usadas:
            continue
        usadas.add(clave)
        adj[u].append(v)
        adj[v].append(u)
        faltan -= 1
    return adj


# ---------------------------------------------------------------------------
# 1. BFS SECUENCIAL (línea base)
# ---------------------------------------------------------------------------
def bfs_secuencial(adj, origen):
    """
    Devuelve dist[v] = cantidad mínima de aristas entre origen y v
    (-1 si v no es alcanzable). Cola FIFO: primero todos los nodos a
    distancia d, después los de distancia d + 1.
    """
    dist = [-1] * len(adj)
    dist[origen] = 0
    cola = deque([origen])
    while cola:
        u = cola.popleft()
        for v in adj[u]:
            if dist[v] == -1:          # "todavía no descubierto"
                dist[v] = dist[u] + 1
                cola.append(v)
    return dist


# ---------------------------------------------------------------------------
# 2. BFS CONCURRENTE POR NIVELES
# ---------------------------------------------------------------------------
# Idea: los nodos de una misma frontera (mismo nivel) son independientes
# entre sí, así que pueden expandirse al mismo tiempo. La dependencia real
# es ENTRE niveles: no se puede empezar el nivel d + 1 hasta conocer
# completo el nivel d. Eso es una barrera de sincronización por nivel.
#
# Diseño para evitar carreras: los trabajadores NO escriben en estructuras
# compartidas. Cada uno recibe un trozo de la frontera y devuelve SU lista
# local de vecinos descubiertos. Solo el coordinador (hilo principal) lee y
# modifica `dist`, y lo hace entre niveles. Sin locks y sin carreras.

_ADJ = None  # grafo visible para los trabajadores (solo lectura)


def iniciar_trabajador(adj):
    """Inicializa el grafo global del trabajador (hilo o proceso)."""
    global _ADJ
    _ADJ = adj


def expandir_trozo(trozo):
    """
    TRABAJADOR: expande un trozo de la frontera. Es una función pura:
    solo lee el grafo y devuelve el conjunto de vecinos de sus nodos.
    Ya elimina duplicados locales usando un set.
    """
    adj = _ADJ
    candidatos = set()
    for u in trozo:
        candidatos.update(adj[u])
    return candidatos


def partir(frontera, k):
    """Reparte la frontera en k trozos contiguos de tamaño casi igual."""
    tam = -(-len(frontera) // k)  # división entera hacia arriba
    return [frontera[i:i + tam] for i in range(0, len(frontera), tam)]


def bfs_concurrente(adj, origen, ejecutor, trabajadores, traza=None):
    """
    BFS por niveles con `trabajadores` tareas por nivel.
    `ejecutor` puede ser ThreadPoolExecutor o ProcessPoolExecutor.

    Devuelve (dist, estadisticas).
    """
    dist = [-1] * len(adj)
    dist[origen] = 0
    frontera = [origen]
    nivel = 0
    est = {"niveles": 0, "aristas_examinadas": 0,
           "candidatos_locales": 0, "duplicados_entre_trabajadores": 0}

    while frontera:
        trozos = partir(frontera, trabajadores)

        # --- fase paralela: cada trabajador expande su trozo ------------
        resultados = list(ejecutor.map(expandir_trozo, trozos))
        # list(...) espera a TODOS: es la barrera de fin de nivel.

        # --- fase secuencial: reunir y eliminar duplicados --------------
        todos = set()
        suma_locales = 0
        for r in resultados:
            suma_locales += len(r)
            todos.update(r)                       # unión = reunir sin repetir
        nueva = [v for v in todos if dist[v] == -1]   # descartar ya visitados
        nivel += 1
        for v in nueva:
            dist[v] = nivel

        est["niveles"] += 1
        est["aristas_examinadas"] += sum(len(adj[u]) for u in frontera)
        est["candidatos_locales"] += suma_locales
        est["duplicados_entre_trabajadores"] += suma_locales - len(todos)

        if traza is not None:
            traza(nivel - 1, frontera, trozos, resultados, todos, nueva)

        frontera = nueva

    return dist, est


# ---------------------------------------------------------------------------
# 4. CORRECCIÓN
# ---------------------------------------------------------------------------
def verificar(adj, dist, origen):
    """
    Comprueba propiedades que definen las distancias mínimas en BFS:
      a) dist[origen] == 0
      b) para toda arista (u, v) alcanzable: |dist[u] - dist[v]| <= 1
      c) todo nodo con dist > 0 tiene un vecino con dist - 1 (camino real)
    """
    assert dist[origen] == 0, "el origen debe estar a distancia 0"
    for u, vecinos in enumerate(adj):
        if dist[u] == -1:
            assert all(dist[v] == -1 for v in vecinos), "vecino de no alcanzable"
            continue
        if u != origen:
            assert any(dist[v] == dist[u] - 1 for v in vecinos), \
                f"el nodo {u} no tiene predecesor a distancia {dist[u] - 1}"
        for v in vecinos:
            assert abs(dist[u] - dist[v]) <= 1, f"arista ({u},{v}) viola |d(u)-d(v)|<=1"
    return True


# ---------------------------------------------------------------------------
# DEMOSTRACIÓN: ¿por qué hay que eliminar duplicados?
# ---------------------------------------------------------------------------
def demo_carrera():
    """
    Dos trabajadores expanden los nodos 1 y 2, ambos vecinos del nodo 3.
    Versión INGENUA: comprobar dist[v] == -1 y después escribir, sin
    protección (check-then-act, igual que la Actividad 9). Una barrera
    fuerza la intercalación mala para que sea reproducible.
    """
    adj = crear_grafo(4, [(0, 1), (0, 2), (1, 3), (2, 3)])

    def correr(con_lock):
        dist = [0, 1, 1, -1]
        siguiente = []
        barrera = threading.Barrier(2)
        lock = threading.Lock()

        def trabajador(u):
            for v in adj[u]:
                if dist[v] == -1:                 # 1) comprobar
                    if not con_lock:
                        barrera.wait()            # ambos comprobaron antes de escribir
                        dist[v] = 2               # 2) escribir
                        siguiente.append(v)
                    else:
                        barrera.wait()
                        with lock:                # sección crítica + re-chequeo
                            if dist[v] == -1:
                                dist[v] = 2
                                siguiente.append(v)

        hilos = [threading.Thread(target=trabajador, args=(u,)) for u in (1, 2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        return siguiente

    return correr(False), correr(True)


# ---------------------------------------------------------------------------
# EJEMPLO PEQUEÑO CON TRAZA
# ---------------------------------------------------------------------------
ARISTAS_EJEMPLO = [(0, 1), (0, 2), (0, 3), (1, 4), (2, 4), (2, 5), (3, 5),
                   (3, 6), (4, 7), (5, 7), (5, 8), (6, 8), (7, 9), (8, 9)]


def ejemplo():
    adj = crear_grafo(10, ARISTAS_EJEMPLO)
    print("=== Lista de adyacencia (10 nodos, 14 aristas) ===")
    for u, vecinos in enumerate(adj):
        print(f"  {u}: {vecinos}")

    d_seq = bfs_secuencial(adj, 0)
    print("\n=== BFS secuencial desde 0 ===")
    print("  distancias:", d_seq)

    def traza(nivel, frontera, trozos, resultados, todos, nueva):
        print(f"\n  Nivel {nivel} -> {nivel + 1}")
        print(f"    frontera                : {frontera}")
        for i, (t, r) in enumerate(zip(trozos, resultados), 1):
            print(f"    trabajador {i}: trozo {t} -> descubre {sorted(r)}")
        print(f"    unión sin duplicados    : {sorted(todos)}")
        print(f"    nuevos (no visitados)   : {sorted(nueva)}")

    print("\n=== BFS concurrente por niveles (2 trabajadores) ===")
    with ThreadPoolExecutor(max_workers=2,
                            initializer=iniciar_trabajador, initargs=(adj,)) as ex:
        d_con, est = bfs_concurrente(adj, 0, ex, 2, traza)
    print("\n  distancias:", d_con)
    print("  estadísticas:", est)
    return adj, d_seq, d_con


if __name__ == "__main__":
    adj, d_seq, d_con = ejemplo()

    print("\n=== Demostración de la condición de carrera ===")
    ingenua, protegida = demo_carrera()
    print(f"  sin protección : siguiente frontera = {ingenua}   (nodo 3 duplicado)")
    print(f"  con lock       : siguiente frontera = {protegida}")

    print("\n=== Pruebas de corrección ===")
    assert d_seq == d_con, "secuencial y concurrente deben coincidir"
    verificar(adj, d_seq, 0)
    print("  ejemplo pequeño: OK")
    for n, m in [(50, 120), (1000, 3000), (5000, 20000)]:
        g = generar_grafo(n, m, semilla=7)
        ref = bfs_secuencial(g, 0)
        verificar(g, ref, 0)
        for k in (1, 2, 3, 4, 8):
            with ThreadPoolExecutor(max_workers=k,
                                    initializer=iniciar_trabajador, initargs=(g,)) as ex:
                d, _ = bfs_concurrente(g, 0, ex, k)
            assert d == ref, f"difiere con n={n}, m={m}, k={k}"
        print(f"  n={n:>5}, m={m:>6}: concurrente == secuencial con 1,2,3,4,8 trabajadores: OK")
    print("\nTodas las pruebas pasaron.")
