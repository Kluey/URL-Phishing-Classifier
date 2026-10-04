import json
import os
import torch
import numpy as np
import requests
from tqdm import tqdm

if os.name == "nt":
    system32_path = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"), "System32"
    )
    current_path = os.environ.get("PATH", "")
    if system32_path.lower() not in {
        path.lower() for path in current_path.split(os.pathsep)
    }:
        os.environ["PATH"] = system32_path + os.pathsep + current_path
import tensorflow as tf

def download_and_load_gpt2(model_size, models_dir):
    allowed_sizes = ("124M", "355M", "774M", "1558M")
    if model_size not in allowed_sizes:
        raise ValueError(f"Model size not in {allowed_sizes}")

    model_dir = os.path.join(models_dir, model_size)
    base_url = "https://openaipublic.blob.core.windows.net/gpt-2/models"
    backup_base_url = "https://f001.backblazeb2.com/file/LLMs-from-scratch/gpt2"
    filenames = [
        "checkpoint",
        "encoder.json",
        "hparams.json",
        "model.ckpt.data-00000-of-00001",
        "model.ckpt.index",
        "model.ckpt.meta",
        "vocab.bpe",
    ]

    os.makedirs(model_dir, exist_ok=True)
    for filename in filenames:
        file_url = "/".join((base_url, model_size, filename))
        backup_url = "/".join((backup_base_url, model_size, filename))
        file_path = os.path.join(model_dir, filename)
        download_file(file_url, file_path, backup_url)

    checkpoint_path = tf.train.latest_checkpoint(model_dir)
    with open(
        os.path.join(model_dir, "hparams.json"), "r", encoding="utf-8"
    ) as settings_file:
        settings = json.load(settings_file)
    params = load_gpt2_params_from_tf_ckpt(checkpoint_path, settings)
    return settings, params


def download_file(url, destination, backup_url=None):
    def attempt_download(download_url):
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        file_size = int(response.headers.get("Content-Length", 0))

        if os.path.exists(destination):
            local_size = os.path.getsize(destination)
            if file_size and file_size == local_size:
                print(f"File already exists and is up-to-date: {destination}")
                return True

        with tqdm(
            total=file_size,
            unit="iB",
            unit_scale=True,
            desc=os.path.basename(download_url),
        ) as progress_bar:
            with open(destination, "wb") as output_file:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        output_file.write(chunk)
                        progress_bar.update(len(chunk))
        return True

    try:
        if attempt_download(url):
            return
    except requests.exceptions.RequestException:
        if backup_url is not None:
            print(f"Primary URL ({url}) failed. Attempting backup URL: {backup_url}")
            try:
                if attempt_download(backup_url):
                    return
            except requests.exceptions.RequestException:
                pass

        backup_detail = f" and backup URL ({backup_url})" if backup_url else ""
        print(
            f"Failed to download from primary URL ({url}){backup_detail}.\n"
            "Check your internet connection or the file availability.\n"
            "For help, visit: "
            "https://github.com/rasbt/LLMs-from-scratch/discussions/273"
        )
    except Exception as exc:
        print(f"An unexpected error occurred: {exc}")


def load_gpt2_params_from_tf_ckpt(ckpt_path, settings):
    params = {"blocks": [{} for _ in range(settings["n_layer"])]}

    for name, _ in tf.train.list_variables(ckpt_path):
        variable_array = np.squeeze(tf.train.load_variable(ckpt_path, name))
        variable_name_parts = name.split("/")[1:]

        target_dict = params
        if variable_name_parts[0].startswith("h"):
            block_number = int(variable_name_parts[0][1:])
            target_dict = params["blocks"][block_number]

        for key in variable_name_parts[1:-1]:
            target_dict = target_dict.setdefault(key, {})

        target_dict[variable_name_parts[-1]] = variable_array

    return params


def assign(left, right):
    if left.shape != right.shape:
        raise ValueError(f"Shape mismatch. Left: {left.shape}, Right: {right.shape}")
    return torch.nn.Parameter(torch.tensor(right))


def load_weights_into_gpt(gpt, params):
    gpt.pos_emb.weight = assign(gpt.pos_emb.weight, params['wpe'])
    gpt.tok_emb.weight = assign(gpt.tok_emb.weight, params['wte'])

    for b in range(len(params["blocks"])):
        gpt.trf_blocks[b].att.qkv.weight = assign(
            gpt.trf_blocks[b].att.qkv.weight,
            params["blocks"][b]["attn"]["c_attn"]["w"].T)
        gpt.trf_blocks[b].att.qkv.bias = assign(
            gpt.trf_blocks[b].att.qkv.bias,
            params["blocks"][b]["attn"]["c_attn"]["b"])
        gpt.trf_blocks[b].att.proj.weight = assign(
            gpt.trf_blocks[b].att.proj.weight,
            params["blocks"][b]["attn"]["c_proj"]["w"].T)

        gpt.trf_blocks[b].att.proj.bias = assign(
            gpt.trf_blocks[b].att.proj.bias,
            params["blocks"][b]["attn"]["c_proj"]["b"])
        gpt.trf_blocks[b].ff.layers[0].weight = assign(
            gpt.trf_blocks[b].ff.layers[0].weight,
            params["blocks"][b]["mlp"]["c_fc"]["w"].T)
        gpt.trf_blocks[b].ff.layers[0].bias = assign(
            gpt.trf_blocks[b].ff.layers[0].bias,
            params["blocks"][b]["mlp"]["c_fc"]["b"])
        gpt.trf_blocks[b].ff.layers[2].weight = assign(
            gpt.trf_blocks[b].ff.layers[2].weight,
            params["blocks"][b]["mlp"]["c_proj"]["w"].T)
        gpt.trf_blocks[b].ff.layers[2].bias = assign(
            gpt.trf_blocks[b].ff.layers[2].bias,
            params["blocks"][b]["mlp"]["c_proj"]["b"])
        gpt.trf_blocks[b].norm1.scale = assign(
            gpt.trf_blocks[b].norm1.scale,
            params["blocks"][b]["ln_1"]["g"])
        gpt.trf_blocks[b].norm1.shift = assign(
            gpt.trf_blocks[b].norm1.shift,
            params["blocks"][b]["ln_1"]["b"])
        gpt.trf_blocks[b].norm2.scale = assign(
            gpt.trf_blocks[b].norm2.scale,
            params["blocks"][b]["ln_2"]["g"])
        gpt.trf_blocks[b].norm2.shift = assign(
            gpt.trf_blocks[b].norm2.shift,
            params["blocks"][b]["ln_2"]["b"])
        
    gpt.final_norm.scale = assign(gpt.final_norm.scale, params["g"])
    gpt.final_norm.shift = assign(gpt.final_norm.shift, params["b"])
    gpt.out_head.weight = assign(gpt.out_head.weight, params["wte"])


__all__ = [
    "download_and_load_gpt2",
    "download_file",
    "load_gpt2_params_from_tf_ckpt",
    "assign",
    "load_weights_into_gpt",
]