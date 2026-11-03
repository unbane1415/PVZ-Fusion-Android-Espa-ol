#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  PvZ Fusion Localization & Dump Toolkit
  Herramienta automatizada para extracción de textos, dumps y localización
  de Plants vs. Zombies Fusion (RH) para futuras versiones (4.2, 5.0, etc.).
=============================================================================
"""

import os
import sys
import json
import struct
import re
import shutil
import argparse
from typing import Dict, List, Tuple, Set, Any, Optional

DEFAULT_BASE_DIR = "/home/jean/Desktop/PVZ_2"
DEFAULT_GIT_DIR = "/home/jean/Desktop/PVZ/git"
METADATA_REL_PATH = "PlantsVsZombiesRH_Data/il2cpp_data/Metadata/global-metadata.dat"

# Expresión regular para caracteres CJK (Chino, Japonés, Coreano)
CJK_REGEX = re.compile(r'[\u4e00-\u9fff]')

class MetadataParser:
    """Lee y decodifica global-metadata.dat de IL2CPP (v24 a v31+)."""

    def __init__(self, metadata_path: str):
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"No se encontró global-metadata.dat en: {metadata_path}")
        self.path = metadata_path
        with open(metadata_path, 'rb') as f:
            self.data = f.read()

        self.sanity, self.version = struct.unpack_from('<II', self.data, 0)
        if self.sanity != 0xFAB11BAF:
            raise ValueError(f"Firma de metadata inválida: {hex(self.sanity)} (esperado 0xFAB11BAF)")

        # Offsets del encabezado en v29-v31
        self.string_literal_offset, self.string_literal_size = struct.unpack_from('<II', self.data, 8)
        self.string_literal_data_offset, self.string_literal_data_size = struct.unpack_from('<II', self.data, 16)
        self.string_offset, self.string_size = struct.unpack_from('<II', self.data, 24)
        
        # TypeDefs y Fields
        self.type_defs_offset, self.type_defs_size = struct.unpack_from('<II', self.data, 40)
        self.fields_offset, self.fields_size = struct.unpack_from('<II', self.data, 48)

    def extract_string_literals(self) -> List[Dict[str, Any]]:
        """Extrae todas las cadenas literales del juego con su índice IL2CPP."""
        count = self.string_literal_size // 8
        results = []
        for i in range(count):
            length, off = struct.unpack_from('<II', self.data, self.string_literal_offset + i * 8)
            raw = self.data[self.string_literal_data_offset + off : self.string_literal_data_offset + off + length]
            try:
                val = raw.decode('utf-8')
            except UnicodeDecodeError:
                val = raw.decode('utf-8', errors='replace')
            results.append({'index': i, 'value': val})
        return results

    def get_string(self, offset: int) -> str:
        """Lee una cadena terminada en null de la tabla de cadenas de nombres."""
        end = self.data.find(b'\0', offset)
        if end == -1:
            end = len(self.data)
        return self.data[offset:end].decode('utf-8', errors='replace')


class AlmanacMapper:
    """Gestiona la correspondencia oficial de nombres de Plantas y Zombis del Almanaque."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.cn_to_es_plants: Dict[str, str] = {}
        self.cn_to_es_zombies: Dict[str, str] = {}
        self._load_mappings()

    def _load_mappings(self):
        # 1. Plantas
        cn_p_path = os.path.join(self.base_dir, "Translated/Dumps/LawnStrings.json")
        es_p_path = os.path.join(self.base_dir, "Translated/Localization/Spanish/Almanac/LawnStringsTranslate.json")
        if os.path.exists(cn_p_path) and os.path.exists(es_p_path):
            try:
                with open(cn_p_path, 'r', encoding='utf-8') as f:
                    cn_plants = json.load(f).get('plants', [])
                with open(es_p_path, 'r', encoding='utf-8') as f:
                    es_plants = json.load(f).get('plants', [])
                
                cn_map = {p['seedType']: p['name'] for p in cn_plants if 'seedType' in p and 'name' in p}
                es_map = {p['seedType']: p['name'] for p in es_plants if 'seedType' in p and 'name' in p}
                for sid, name in cn_map.items():
                    if sid in es_map:
                        self.cn_to_es_plants[name] = es_map[sid]
            except Exception as e:
                print(f"[Aviso] No se pudo cargar el mapeo completo de plantas: {e}")

        # 2. Zombis
        cn_z_path = os.path.join(self.base_dir, "Translated/Dumps/ZombieStrings.json")
        es_z_path = os.path.join(self.base_dir, "Translated/Localization/Spanish/Almanac/ZombieStringsTranslate.json")
        if os.path.exists(cn_z_path) and os.path.exists(es_z_path):
            try:
                with open(cn_z_path, 'r', encoding='utf-8') as f:
                    cn_zombies = json.load(f).get('zombies', [])
                with open(es_z_path, 'r', encoding='utf-8') as f:
                    es_zombies = json.load(f).get('zombies', [])
                
                cn_z_map = {z['zombieType']: z['name'] for z in cn_zombies if 'zombieType' in z and 'name' in z}
                es_z_map = {z['zombieType']: z['name'] for z in es_zombies if 'zombieType' in z and 'name' in z}
                for zid, name in cn_z_map.items():
                    if zid in es_z_map:
                        self.cn_to_es_zombies[name] = es_z_map[zid]
            except Exception as e:
                print(f"[Aviso] No se pudo cargar el mapeo completo de zombis: {e}")

    def translate_plant_name(self, cn_name: str) -> Optional[str]:
        return self.cn_to_es_plants.get(cn_name)

    def translate_zombie_name(self, cn_name: str) -> Optional[str]:
        return self.cn_to_es_zombies.get(cn_name)

    def auto_replace_tags(self, text: str) -> str:
        """Reemplaza nombres chinos dentro de etiquetas <color=red>...</color> por su nombre oficial en español."""
        def repl(match):
            color = match.group(1)
            cn_word = match.group(2)
            es_word = self.cn_to_es_plants.get(cn_word) or self.cn_to_es_zombies.get(cn_word) or cn_word
            return f"<color={color}>{es_word}</color>"
        return re.sub(r'<color=([#a-zA-Z0-9]+)>(.*?)</color>', repl, text)


class UntranslatedScanner:
    """Escanea y encuentra cadenas chinas no traducidas en la nueva versión."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def gather_all_translated_strings(self) -> Set[str]:
        """Recopila todas las cadenas originales en chino que ya están traducidas al español."""
        known_strings: Set[str] = set()

        loc_dir = os.path.join(self.base_dir, "Translated/Localization/Spanish")
        dump_dir = os.path.join(self.base_dir, "Translated/Dumps")

        # 1. Strings/translation_strings.json
        ts_path = os.path.join(loc_dir, "Strings/translation_strings.json")
        if os.path.exists(ts_path):
            with open(ts_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
                known_strings.update(d.keys())

        # 2. travel_buffs.json (Dumps)
        tb_dump_path = os.path.join(dump_dir, "travel_buffs.json")
        if os.path.exists(tb_dump_path):
            with open(tb_dump_path, 'r', encoding='utf-8') as f:
                tb = json.load(f)
                for sec in tb.values():
                    if isinstance(sec, dict):
                        for item in sec.values():
                            if isinstance(item, dict):
                                if item.get('desc'):
                                    known_strings.add(item['desc'])
                                if item.get('name'):
                                    known_strings.add(item['name'])

        # 3. tips, help y otros
        for f_name in ["tips_fs.json", "tips_iz.json"]:
            p = os.path.join(dump_dir, f_name)
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        d = json.load(f)
                        if isinstance(d, dict):
                            known_strings.update(d.keys())
                except:
                    pass

        return known_strings

    def find_missing(self, all_literals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Encuentra cadenas con caracteres CJK que no están en el diccionario de traducciones."""
        known = self.gather_all_translated_strings()
        missing = []
        seen = set()

        # Filtros de exclusión: rutas internas, nombres de clases o archivos que no se traducen
        ignore_prefixes = ("Assets/", "Packages/", "TextMeshPro", "UnityEngine", "m_", "System.", "Il2Cpp")

        for item in all_literals:
            val = item['value'].strip()
            if not val:
                continue
            if not CJK_REGEX.search(val):
                continue
            if val in known:
                continue
            if val in seen:
                continue
            if val.startswith(ignore_prefixes):
                continue

            seen.add(val)
            missing.append({
                'index': item['index'],
                'chinese': val
            })

        return missing


class TravelBuffManager:
    """Gestiona y verifica la integridad de travel_buffs.json."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.dump_path = os.path.join(base_dir, "Translated/Dumps/travel_buffs.json")
        self.trans_path = os.path.join(base_dir, "Translated/Localization/Spanish/Strings/travel_buffs.json")

    def load_files(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        with open(self.dump_path, 'r', encoding='utf-8') as f:
            dump = json.load(f)
        with open(self.trans_path, 'r', encoding='utf-8') as f:
            trans = json.load(f)
        return dump, trans

    def save_files(self, dump: Dict[str, Any], trans: Dict[str, Any]):
        def sort_subdicts(d):
            return {k: d[k] for k in sorted(d.keys(), key=lambda x: int(x) if x.isdigit() else x)}

        for sec in dump:
            if isinstance(dump[sec], dict):
                dump[sec] = sort_subdicts(dump[sec])
        for sec in trans:
            if isinstance(trans[sec], dict):
                trans[sec] = sort_subdicts(trans[sec])

        with open(self.dump_path, 'w', encoding='utf-8') as f:
            json.dump(dump, f, ensure_ascii=False, indent=2)
        with open(self.trans_path, 'w', encoding='utf-8') as f:
            json.dump(trans, f, ensure_ascii=False, indent=2)

    def check_outdated_descriptions(self, game_strings: Set[str]) -> List[Tuple[str, str, str]]:
        dump, _ = self.load_files()
        outdated = []
        for sec, items in dump.items():
            if not isinstance(items, dict):
                continue
            for k, v in items.items():
                desc = v.get('desc', '').strip()
                if desc and desc not in game_strings:
                    outdated.append((sec, k, desc))
        return outdated

    def check_parity(self) -> Tuple[bool, List[str]]:
        dump, trans = self.load_files()
        reports = []
        is_ok = True

        sections = ['advancedBuffs', 'ultimateBuffs', 'debuffs', 'unlocks', 'investmentBuffs', 'synergies']
        for sec in sections:
            d_keys = set(dump.get(sec, {}).keys())
            t_keys = set(trans.get(sec, {}).keys())
            
            missing_in_trans = d_keys - t_keys
            missing_in_dump = t_keys - d_keys

            if missing_in_trans:
                is_ok = False
                reports.append(f"[{sec}] Claves en DUMP que faltan en TRADUCCIÓN: {sorted(missing_in_trans, key=lambda x: int(x) if x.isdigit() else x)}")
            if missing_in_dump:
                is_ok = False
                reports.append(f"[{sec}] Claves en TRADUCCIÓN que faltan en DUMP: {sorted(missing_in_dump, key=lambda x: int(x) if x.isdigit() else x)}")

        return is_ok, reports

    def generate_translation_template(self, output_path: str, mapper: AlmanacMapper):
        """Genera un archivo plantilla con los textos nuevos o pendientes, sugiriendo nombres del almanaque."""
        dump, trans = self.load_files()
        template = {}

        for sec, items in dump.items():
            if not isinstance(items, dict):
                continue
            for k, v in items.items():
                if k not in trans.get(sec, {}):
                    # Clave completamente faltante
                    desc_cn = v.get('desc', '')
                    name_cn = v.get('name', '')
                    suggested_desc = mapper.auto_replace_tags(desc_cn)
                    template.setdefault(sec, {})[k] = {
                        'chinese_name': name_cn,
                        'chinese_desc': desc_cn,
                        'suggested_desc_with_official_names': suggested_desc,
                        'name_translation': '',
                        'desc_translation': ''
                    }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        return template


def sync_to_git(base_dir: str, git_dir: str) -> List[str]:
    """Sincroniza los dumps y traducciones actualizadas con el repositorio git."""
    copied = []
    pairs = [
        ("Translated/Dumps/travel_buffs.json", "Translated/Dumps/travel_buffs.json"),
        ("Translated/Localization/Spanish/Strings/travel_buffs.json", "Translated/Localization/Spanish/Strings/travel_buffs.json"),
        ("Translated/Localization/Spanish/Strings/translation_strings.json", "Translated/Localization/Spanish/Strings/translation_strings.json"),
        ("Translated/Dumps/strings_4.1_chinese.json", "Translated/Dumps/strings_4.1_chinese.json"),
    ]
    for src_rel, dst_rel in pairs:
        src = os.path.join(base_dir, src_rel)
        dst = os.path.join(git_dir, dst_rel)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(dst_rel)
    return copied


# =============================================================================
# COMANDOS CLI
# =============================================================================

def cmd_dump_metadata(args):
    """Extrae todas las cadenas de global-metadata.dat."""
    base_dir = args.base_dir
    meta_path = args.metadata or os.path.join(base_dir, METADATA_REL_PATH)
    out_path = args.output or os.path.join(base_dir, f"Translated/Dumps/strings_{args.game_version}_chinese.json")

    print(f"[*] Analizando metadata: {meta_path}")
    parser = MetadataParser(meta_path)
    print(f"[+] IL2CPP Metadata versión: {parser.version}")

    literals = parser.extract_string_literals()
    print(f"[+] Cadenas extraídas: {len(literals)}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(literals, f, ensure_ascii=False, indent=2)
    print(f"[✓] Guardado dump completo en: {out_path}")


def cmd_find_untranslated(args):
    """Encuentra textos no traducidos entre el dump nuevo y las traducciones existentes."""
    base_dir = args.base_dir
    meta_path = args.metadata or os.path.join(base_dir, METADATA_REL_PATH)
    out_path = args.output or os.path.join(base_dir, f"Translated/Dumps/untranslated_{args.game_version}.json")

    print(f"[*] Extrayendo cadenas de metadata...")
    parser = MetadataParser(meta_path)
    literals = parser.extract_string_literals()

    scanner = UntranslatedScanner(base_dir)
    print(f"[*] Comparando contra diccionarios en español...")
    missing = scanner.find_missing(literals)
    print(f"[+] Encontradas {len(missing)} cadenas chinas no traducidas.")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(missing, f, ensure_ascii=False, indent=2)
    print(f"[✓] Reporte de textos faltantes guardado en: {out_path}")


def cmd_check_travel(args):
    """Verifica paridad de travel_buffs.json y genera plantilla si faltan textos."""
    base_dir = args.base_dir
    meta_path = args.metadata or os.path.join(base_dir, METADATA_REL_PATH)
    tb_mgr = TravelBuffManager(base_dir)
    mapper = AlmanacMapper(base_dir)

    print("[*] Comprobando paridad de travel_buffs.json (Dumps vs Traducción)...")
    is_ok, reports = tb_mgr.check_parity()
    if is_ok:
        print("[✓] ¡Paridad perfecta! Todas las secciones y claves coinciden.")
    else:
        print("[!] Se encontraron discrepancias de claves:")
        for r in reports:
            print(f"  - {r}")

        template_out = os.path.join(base_dir, "Script/travel_buffs_missing_template.json")
        tpl = tb_mgr.generate_translation_template(template_out, mapper)
        count = sum(len(v) for v in tpl.values())
        if count > 0:
            print(f"[+] Se generó una plantilla de traducción con {count} habilidades en: {template_out}")

    # Verificar si hay descripciones de buffs que hayan cambiado en el juego
    if os.path.exists(meta_path):
        print("[*] Comprobando si alguna descripción en travel_buffs.json cambió en el juego...")
        parser = MetadataParser(meta_path)
        game_literals = parser.extract_string_literals()
        game_strings = {item['value'].strip() for item in game_literals}
        outdated = tb_mgr.check_outdated_descriptions(game_strings)
        if outdated:
            print(f"[!] Se encontraron {len(outdated)} descripciones en travel_buffs.json que no coinciden exactamente con el juego actual:")
            for sec, k, desc in outdated:
                short_desc = desc.replace(chr(10), ' ')[:70]
                print(f"    [{sec}][{k}]: {short_desc}...")
        else:
            print("[✓] Todas las descripciones en travel_buffs.json coinciden con los textos del juego actual.")


def cmd_validate(args):
    """Valida la sintaxis y etiquetas HTML/BBCode en las traducciones."""
    base_dir = args.base_dir
    tb_mgr = TravelBuffManager(base_dir)
    is_ok, reports = tb_mgr.check_parity()

    print("[*] Validación de travel_buffs.json:")
    if is_ok:
        print("  [✓] Estructura y claves 100% sincronizadas.")
    else:
        print("  [X] Error en paridad de claves:")
        for r in reports:
            print(f"      {r}")

    # Validar etiquetas <color> y <nobr>
    trans_path = os.path.join(base_dir, "Translated/Localization/Spanish/Strings/travel_buffs.json")
    with open(trans_path, 'r', encoding='utf-8') as f:
        trans = json.load(f)

    tag_errors = 0
    for sec, items in trans.items():
        if not isinstance(items, dict):
            continue
        for k, v in items.items():
            desc = v.get('desc', '')
            # Verificar tags color
            opens_c = desc.count('<color=')
            closes_c = desc.count('</color>')
            if opens_c != closes_c:
                print(f"  [!] Desbalance de <color> en [{sec}][{k}]: {opens_c} abiertos vs {closes_c} cerrados")
                tag_errors += 1
            # Verificar tags nobr
            opens_n = desc.count('<nobr>')
            closes_n = desc.count('</nobr>')
            if opens_n != closes_n:
                print(f"  [!] Desbalance de <nobr> en [{sec}][{k}]: {opens_n} abiertos vs {closes_n} cerrados")
                tag_errors += 1

    if tag_errors == 0:
        print("  [✓] Todas las etiquetas <color> y <nobr> están perfectamente balanceadas.")


def cmd_sync(args):
    """Sincroniza archivos entre PVZ_2 y el repositorio git."""
    base_dir = args.base_dir
    git_dir = args.git_dir
    print(f"[*] Sincronizando hacia git: {git_dir}")
    copied = sync_to_git(base_dir, git_dir)
    for c in copied:
        print(f"  [✓] Sincronizado: {c}")
    print("[✓] Sincronización completada.")


def cmd_update_all(args):
    """Flujo completo automatizado para nuevas versiones del juego."""
    print("=" * 70)
    print(f" EJECUTANDO FLUJO COMPLETO DE ACTUALIZACIÓN (Versión: {args.game_version})")
    print("=" * 70)
    cmd_dump_metadata(args)
    print("-" * 70)
    cmd_find_untranslated(args)
    print("-" * 70)
    cmd_check_travel(args)
    print("-" * 70)
    cmd_validate(args)
    print("-" * 70)
    if args.auto_sync:
        cmd_sync(args)
    print("=" * 70)
    print("[✓] Proceso finalizado. Revisa los archivos generados en Translated/Dumps/")


def main():
    parser = argparse.ArgumentParser(
        description="Toolkit de Localización y Dumps para PvZ Fusion",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--base-dir', default=DEFAULT_BASE_DIR, help="Ruta al directorio base del juego (PVZ_2)")
    parser.add_argument('--git-dir', default=DEFAULT_GIT_DIR, help="Ruta al repositorio git")
    parser.add_argument('--game-version', default="4.1", help="Versión del juego (ej: 4.1, 4.2, 5.0)")
    parser.add_argument('--metadata', default=None, help="Ruta explícita a global-metadata.dat")

    subparsers = parser.add_subparsers(dest="subcommand", help="Comandos disponibles")

    # dump-metadata
    p_dump = subparsers.add_parser("dump-metadata", help="Extraer cadenas de global-metadata.dat")
    p_dump.add_argument("-o", "--output", help="Ruta del archivo JSON de salida")

    # find-untranslated
    p_untrans = subparsers.add_parser("find-untranslated", help="Encontrar textos chinos no traducidos")
    p_untrans.add_argument("-o", "--output", help="Ruta del archivo JSON de salida")

    # check-travel
    subparsers.add_parser("check-travel", help="Comprobar paridad y faltantes en travel_buffs.json")

    # validate
    subparsers.add_parser("validate", help="Validar sintaxis, paridad y etiquetas HTML de traducciones")

    # sync
    subparsers.add_parser("sync", help="Sincronizar dumps y traducciones con la carpeta git")

    # update-all
    p_all = subparsers.add_parser("update-all", help="Ejecutar el pipeline completo de extracción y reporte")
    p_all.add_argument("--auto-sync", action="store_true", help="Sincronizar con git automáticamente al terminar")
    p_all.add_argument("-o", "--output", help="Salida para dump de metadata")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "dump-metadata": cmd_dump_metadata,
        "find-untranslated": cmd_find_untranslated,
        "check-travel": cmd_check_travel,
        "validate": cmd_validate,
        "sync": cmd_sync,
        "update-all": cmd_update_all,
    }

    cmds[args.subcommand](args)


if __name__ == "__main__":
    main()
