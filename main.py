#!/usr/env/bin python3

"""
Generate training and test images.
"""
import traceback
import numpy as np

import multiprocessing as mp
from itertools import repeat
import os

import cv2

from utils.config import load_config
from utils.timer import Timer
from parse_args import parse_args
import utils.utils as utils
import utils.font_utils as font_utils
from textfiller.corpus import RandomCorpus, ChnCorpus, EngCorpus, get_corpus
from textfiller.renderer import Renderer
from tenacity import retry

lock = mp.Lock()
counter = mp.Value('i', 0)
STOP_TOKEN = 'kill'

flags = parse_args()
cfg = load_config(flags.config_file)

fonts = font_utils.get_font_paths(flags.fonts_dir)
bgs = utils.load_bgs(flags.bg_dir)

corpus = get_corpus(flags.corpus_mode, flags.chars_file, flags.corpus_dir, flags.length)

renderer = Renderer(corpus, fonts, bgs, cfg,
                    height=flags.img_height,
                    width=flags.img_width,
                    clip_max_chars=flags.clip_max_chars,
                    debug=flags.debug,
                    gpu=flags.gpu,
                    strict=flags.strict,vertical=flags.vertical)


def start_listen(q, fname):
    """ listens for messages on the q, writes to file. """

    f = open(fname, mode='a', encoding='utf-8')
    while 1:
        m = q.get()
        if m == STOP_TOKEN:
            break
        try:
            f.write(str(m) + '\n')
        except:
            traceback.print_exc()

        with lock:
            if counter.value % 1000 == 0:
                f.flush()
    f.close()


@retry
def gen_img_retry(renderer):
    try:
        return renderer.gen_img()
    except Exception:
        print("Retry gen_img")
        raise Exception


def generate_img(img_index, q):
    global flags, lock, counter
    # Make sure different process has different random seed
    np.random.seed()

    im, word = gen_img_retry(renderer)

    base_name = '{:08d}'.format(img_index)

    if not flags.viz:
        fname = os.path.join(flags.save_dir, base_name + '.jpg')
        cv2.imwrite(fname, im)

        label = "{} {}".format(base_name, word)
        q.put(label)

        with lock:
            counter.value += 1
            print_end = '\n' if counter.value == flags.num_img else '\r'
            if counter.value % 100 == 0 or counter.value == flags.num_img:
                print("{}/{} {:2d}%".format(counter.value,
                                            flags.num_img,
                                            int(counter.value / flags.num_img * 100)),
                      end=print_end)
    else:
        utils.viz_img(im)


def sort_labels(tmp_label_fname, label_fname):
    lines = []
    with open(tmp_label_fname, mode='r', encoding='utf-8') as f:
        lines = f.readlines()

    lines = sorted(lines)
    with open(label_fname, mode='w', encoding='utf-8') as f:
        for line in lines:
            f.write(line[9:])


def restore_exist_labels(label_path):
    # 如果目标目录存在 labels.txt 则向该目录中追加图片
    start_index = 0
    if os.path.exists(label_path):
        start_index = len(utils.load_chars(label_path))
        print('Generate more text images in %s. Start index %d' % (flags.save_dir, start_index))
    else:
        print('Generate text images in %s' % flags.save_dir)
    return start_index


if __name__ == "__main__":
    if flags.viz == 1:
        flags.num_processes = 1

    tmp_label_path = os.path.join(flags.save_dir, 'tmp_labels.txt')
    label_path = os.path.join(flags.save_dir, 'labels.txt')

    manager = mp.Manager()
    q = manager.Queue()

    start_index = restore_exist_labels(label_path)

    timer = Timer(Timer.SECOND)
    timer.start()
    with mp.Pool(processes=flags.num_processes) as pool:
        if not flags.viz:
            pool.apply_async(start_listen, (q, tmp_label_path))

        pool.starmap(generate_img, zip(range(start_index, start_index + flags.num_img), repeat(q)))

        q.put(STOP_TOKEN)
        pool.close()
        pool.join()
    timer.end("Job Done!")

    if not flags.viz:
        sort_labels(tmp_label_path, label_path)
