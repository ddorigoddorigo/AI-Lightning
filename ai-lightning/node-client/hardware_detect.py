"""
Hardware detection module for AI Lightning Node Client.

Rileva CPU, RAM, GPU e VRAM del sistema.
"""
import os
import sys
import subprocess
import platform
import json
import logging

logger = logging.getLogger('HardwareDetect')


def get_cpu_info():
    """Rileva informazioni sulla CPU."""
    info = {
        'cores_physical': 1,
        'cores_logical': 1,
        'name': 'Unknown CPU',
        'frequency_mhz': 0
    }
    
    try:
        import multiprocessing
        info['cores_logical'] = multiprocessing.cpu_count()
        
        if sys.platform == 'win32':
            # Windows
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                info['name'] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
                info['frequency_mhz'] = winreg.QueryValueEx(key, "~MHz")[0]
                winreg.CloseKey(key)
            except:
                pass
            
            # Conta core fisici
            try:
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'NumberOfCores'],
                    capture_output=True, text=True
                )
                for line in result.stdout.strip().split('\n'):
                    if line.strip().isdigit():
                        info['cores_physical'] = int(line.strip())
                        break
            except:
                info['cores_physical'] = info['cores_logical'] // 2
                
        else:
            # Linux
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                for line in cpuinfo.split('\n'):
                    if 'model name' in line:
                        info['name'] = line.split(':')[1].strip()
                        break
                
                # Core fisici
                result = subprocess.run(['lscpu'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if 'Core(s) per socket' in line:
                        cores = int(line.split(':')[1].strip())
                    if 'Socket(s)' in line:
                        sockets = int(line.split(':')[1].strip())
                info['cores_physical'] = cores * sockets
            except:
                pass
    except Exception as e:
        logger.error(f"Error detecting CPU: {e}")
    
    return info


def get_ram_info():
    """Rileva quantità e velocità della RAM."""
    result = {
        'total_gb': 0,
        'available_gb': 0,
        'speed_mhz': 0,
        'type': 'Unknown'
    }
    
    try:
        if sys.platform == 'win32':
            import ctypes
            
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            
            result['total_gb'] = round(stat.ullTotalPhys / (1024**3), 1)
            result['available_gb'] = round(stat.ullAvailPhys / (1024**3), 1)
            
            # Rileva velocità RAM su Windows con wmic
            try:
                speed_result = subprocess.run(
                    ['wmic', 'memorychip', 'get', 'speed'],
                    capture_output=True, text=True, timeout=10
                )
                speeds = []
                for line in speed_result.stdout.strip().split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        speeds.append(int(line))
                if speeds:
                    result['speed_mhz'] = max(speeds)  # Usa la velocità più alta
            except:
                pass
            
            # Rileva tipo RAM (DDR3, DDR4, DDR5)
            try:
                type_result = subprocess.run(
                    ['wmic', 'memorychip', 'get', 'SMBIOSMemoryType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in type_result.stdout.strip().split('\n'):
                    line = line.strip()
                    if line.isdigit():
                        mem_type = int(line)
                        # SMBIOSMemoryType codes
                        type_map = {
                            20: 'DDR',
                            21: 'DDR2',
                            22: 'DDR2',
                            24: 'DDR3',
                            26: 'DDR4',
                            34: 'DDR5'
                        }
                        result['type'] = type_map.get(mem_type, f'Type{mem_type}')
                        break
            except:
                pass
                
        else:
            # Linux - quantità RAM
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            total = available = 0
            for line in meminfo.split('\n'):
                if 'MemTotal' in line:
                    total = int(line.split()[1]) / (1024**2)
                elif 'MemAvailable' in line:
                    available = int(line.split()[1]) / (1024**2)
            
            result['total_gb'] = round(total, 1)
            result['available_gb'] = round(available, 1)
            
            # Velocità RAM su Linux con dmidecode (richiede root)
            try:
                speed_result = subprocess.run(
                    ['sudo', 'dmidecode', '-t', 'memory'],
                    capture_output=True, text=True, timeout=10
                )
                for line in speed_result.stdout.split('\n'):
                    if 'Speed:' in line and 'Unknown' not in line and 'Configured' not in line:
                        speed_str = line.split(':')[1].strip().split()[0]
                        if speed_str.isdigit():
                            result['speed_mhz'] = int(speed_str)
                            break
                    if 'Type:' in line and 'DDR' in line:
                        result['type'] = line.split(':')[1].strip()
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error detecting RAM: {e}")
    
    return result


def get_nvidia_gpus():
    """Rileva GPU NVIDIA con nvidia-smi."""
    gpus = []
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,name,memory.total,memory.free,driver_version', 
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 4:
                        gpus.append({
                            'index': int(parts[0]),
                            'name': parts[1],
                            'vram_total_mb': int(float(parts[2])),
                            'vram_free_mb': int(float(parts[3])),
                            'driver': parts[4] if len(parts) > 4 else 'Unknown',
                            'type': 'nvidia',
                            'cuda': True
                        })
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Error detecting NVIDIA GPUs: {e}")
    
    return gpus


def get_amd_gpus_windows():
    """Rileva GPU AMD su Windows."""
    gpus = []
    try:
        # Usa WMI per rilevare GPU AMD
        result = subprocess.run(
            ['wmic', 'path', 'win32_VideoController', 'get', 
             'Name,AdapterRAM,DriverVersion', '/format:csv'],
            capture_output=True, text=True
        )
        
        for line in result.stdout.strip().split('\n'):
            if 'AMD' in line or 'Radeon' in line:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 3:
                    vram = 0
                    try:
                        vram = int(parts[1]) // (1024**2) if parts[1] else 0
                    except:
                        pass
                    
                    gpus.append({
                        'index': len(gpus),
                        'name': parts[2] if len(parts) > 2 else 'AMD GPU',
                        'vram_total_mb': vram,
                        'vram_free_mb': vram,  # Non possiamo saperlo senza ROCm
                        'driver': parts[3] if len(parts) > 3 else 'Unknown',
                        'type': 'amd',
                        'rocm': False,  # Verificare se ROCm è installato
                        'vulkan': True
                    })
    except Exception as e:
        logger.error(f"Error detecting AMD GPUs: {e}")
    
    return gpus


def get_amd_gpus_linux():
    """Rileva GPU AMD su Linux con ROCm."""
    gpus = []
    try:
        result = subprocess.run(
            ['rocm-smi', '--showmeminfo', 'vram', '--json'],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for card_id, info in data.items():
                if card_id.startswith('card'):
                    gpus.append({
                        'index': int(card_id.replace('card', '')),
                        'name': f'AMD GPU {card_id}',
                        'vram_total_mb': info.get('VRAM Total Memory (B)', 0) // (1024**2),
                        'vram_free_mb': info.get('VRAM Total Used Memory (B)', 0) // (1024**2),
                        'type': 'amd',
                        'rocm': True
                    })
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Error detecting AMD GPUs with ROCm: {e}")
    
    return gpus


def get_gpu_info():
    """Rileva tutte le GPU del sistema."""
    gpus = []
    
    # Prova NVIDIA
    nvidia_gpus = get_nvidia_gpus()
    gpus.extend(nvidia_gpus)
    
    # Prova AMD
    if sys.platform == 'win32':
        amd_gpus = get_amd_gpus_windows()
    else:
        amd_gpus = get_amd_gpus_linux()
    
    # Aggiungi solo se non già trovate
    for gpu in amd_gpus:
        if not any(g['name'] == gpu['name'] for g in gpus):
            gpus.append(gpu)
    
    # Se nessuna GPU trovata, fallback a WMI/lspci
    if not gpus:
        try:
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['wmic', 'path', 'win32_VideoController', 'get', 
                     'Name,AdapterRAM', '/format:csv'],
                    capture_output=True, text=True
                )
                
                for line in result.stdout.strip().split('\n')[1:]:
                    if line.strip():
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 2 and parts[1]:
                            vram = 0
                            try:
                                vram = int(parts[2]) // (1024**2) if len(parts) > 2 and parts[2] else 0
                            except:
                                pass
                            
                            name = parts[1] if len(parts) > 1 else 'Unknown GPU'
                            
                            # Determina tipo
                            gpu_type = 'unknown'
                            if 'nvidia' in name.lower() or 'geforce' in name.lower():
                                gpu_type = 'nvidia'
                            elif 'amd' in name.lower() or 'radeon' in name.lower():
                                gpu_type = 'amd'
                            elif 'intel' in name.lower():
                                gpu_type = 'intel'
                            
                            gpus.append({
                                'index': len(gpus),
                                'name': name,
                                'vram_total_mb': vram,
                                'vram_free_mb': vram,
                                'type': gpu_type
                            })
            else:
                result = subprocess.run(['lspci'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if 'VGA' in line or '3D' in line:
                        name = line.split(':')[-1].strip()
                        gpus.append({
                            'index': len(gpus),
                            'name': name,
                            'vram_total_mb': 0,
                            'vram_free_mb': 0,
                            'type': 'unknown'
                        })
        except Exception as e:
            logger.error(f"Error in GPU fallback detection: {e}")
    
    return gpus


def get_disk_info(path=None):
    """Rileva spazio disco disponibile.
    
    Args:
        path: Path da controllare (default: directory corrente o home)
        
    Returns:
        dict con total_gb, free_gb, used_gb, percent_used
    """
    info = {
        'total_gb': 0,
        'free_gb': 0,
        'used_gb': 0,
        'percent_used': 0
    }
    
    try:
        import shutil
        
        # Usa la directory specificata, o la home, o la directory corrente
        if not path:
            path = os.path.expanduser('~')
        
        total, used, free = shutil.disk_usage(path)
        
        info['total_gb'] = round(total / (1024**3), 1)
        info['free_gb'] = round(free / (1024**3), 1)
        info['used_gb'] = round(used / (1024**3), 1)
        info['percent_used'] = round((used / total) * 100, 1) if total > 0 else 0
        
    except Exception as e:
        logger.error(f"Error getting disk info: {e}")
    
    return info


def get_system_info():
    """Rileva tutte le informazioni hardware del sistema."""
    info = {
        'platform': platform.system(),
        'platform_release': platform.release(),
        'architecture': platform.machine(),
        'cpu': get_cpu_info(),
        'ram': get_ram_info(),
        'gpus': get_gpu_info(),
        'disk': get_disk_info()
    }
    
    # Calcola VRAM totale
    total_vram = sum(gpu.get('vram_total_mb', 0) for gpu in info['gpus'])
    info['total_vram_mb'] = total_vram
    
    # Determina capacità massima del modello (approssimativa)
    # ~1GB VRAM per 1B parametri in Q4
    info['max_model_params_b'] = round(total_vram / 1000, 1) if total_vram > 0 else 0
    
    return info


def format_system_info(info):
    """Formatta le info di sistema in stringa leggibile."""
    # Formatta info RAM con velocità
    ram_info = info['ram']
    ram_str = f"{ram_info['total_gb']} GB"
    if ram_info.get('type') and ram_info['type'] != 'Unknown':
        ram_str += f" {ram_info['type']}"
    if ram_info.get('speed_mhz') and ram_info['speed_mhz'] > 0:
        ram_str += f"-{ram_info['speed_mhz']}"
    
    lines = [
        f"Sistema: {info['platform']} {info['platform_release']} ({info['architecture']})",
        f"",
        f"CPU: {info['cpu']['name']}",
        f"  - Core fisici: {info['cpu']['cores_physical']}",
        f"  - Core logici: {info['cpu']['cores_logical']}",
        f"",
        f"RAM: {ram_str} ({ram_info['available_gb']} GB disponibili)",
        f""
    ]
    
    if info['gpus']:
        lines.append(f"GPU ({len(info['gpus'])} rilevate):")
        for gpu in info['gpus']:
            vram_gb = gpu.get('vram_total_mb', 0) / 1024
            lines.append(f"  [{gpu['index']}] {gpu['name']}")
            lines.append(f"      VRAM: {vram_gb:.1f} GB ({gpu.get('vram_total_mb', 0)} MB)")
            lines.append(f"      Tipo: {gpu.get('type', 'unknown').upper()}")
    else:
        lines.append("GPU: Nessuna GPU rilevata (verrà usata la CPU)")
    
    lines.append(f"")
    lines.append(f"VRAM Totale: {info['total_vram_mb']} MB")
    lines.append(f"Modello max stimato: ~{info['max_model_params_b']}B parametri (Q4)")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    # Test
    logging.basicConfig(level=logging.DEBUG)
    info = get_system_info()
    print(format_system_info(info))
    print("\n--- JSON ---")
    print(json.dumps(info, indent=2))
