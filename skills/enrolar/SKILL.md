---
name: enrolar
description: Prepara este ordenador para todos los NAS del inventario de qnap-tools (clave de host y clave SSH). Úsala al instalar el plugin en un ordenador nuevo o tras importar un inventario.
---

# Enrolar este ordenador en la flota

Cada ordenador tiene su propia clave SSH y su propia lista de claves de host: no se copian de
un equipo a otro. Lo que sí se lleva es el **inventario** (nombres, IP y puertos, sin secretos).
Esta skill deja un ordenador nuevo listo para toda la flota.

## Cuándo hace falta

- Se ha instalado el plugin en otro ordenador y se quiere usar con los mismos NAS.
- Se ha reinstalado el plugin (desinstalarlo borra su carpeta de datos: inventario y clave).

## Pasos

1. Comprueba que el plugin está configurado con el usuario y la contraseña SSH comunes
   (`/plugin` → qnap-tools → configurar).
2. Si el inventario viene de otro ordenador:
   - allí, `inventario_exportar(ruta)` lo guarda en un fichero `.toml` (no contiene contraseñas);
   - aquí, `inventario_importar(ruta)` lo incorpora. Enseña qué se ha añadido y los
     `conflictos`; una entrada que ya existe con otros datos solo se cambia con
     `sobrescribir=true`, y eso se le pregunta al usuario.
3. Enseña al usuario la lista de NAS (`nas_lista`) y que confirme que las direcciones son las
   suyas: el enrolado envía la contraseña común a cada una de ellas. Un inventario importado
   de un fichero que no sea de confianza no se enrola.
4. Avisa de lo que va a pasar y lanza `nas_enrolar()`. En cada NAS del inventario:
   - entra por contraseña y **fija su clave de host** en este ordenador;
   - en los que no están marcados como "solo contraseña", **escribe en el NAS** la clave
     pública de este ordenador (`~/.ssh/authorized_keys` del usuario). Es la única escritura
     que hace el plugin.
5. Enseña el resultado NAS por NAS: la **huella de host**, con qué se entra desde ahora
   (`clave` o `contrasena`) y, si lo hay, el `aviso` o el `error` tal cual.
6. Termina con `nas_comprobar("todos")` para confirmar acceso, sudo y sistema de cada uno.

## Notas

- Un NAS que falla no impide enrolar los demás: repite solo cuando el usuario haya arreglado
  la causa (NAS apagado, usuario sin SSH, contraseña distinta).
- La clave instalada en un NAS por otro ordenador no se toca: cada equipo añade la suya.
- Antes de desinstalar el plugin, exporta el inventario si quieres conservarlo.
