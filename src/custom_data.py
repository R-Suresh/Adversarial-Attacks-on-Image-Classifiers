import os

import numpy as np
import pandas as pd
from PIL import Image

import torch
import torchvision
import torchvision.transforms as transforms
from torch.utils.data import Dataset



class HighResolutionDataset(Dataset):
    '''
        Creates a custom dataset for the High Resolution images
        of the NIPS 2017 Adversarial Examples Challenge
    '''
    def __init__(self, main_dir, transform):
        self.main_dir = main_dir
        self.transform = transform

        self.all_imgs = [file for file in os.listdir(main_dir) if file.endswith('.png')]
        self.df = pd.read_csv('./datasets/high_resolution/images.csv', header=0)

    def __len__(self):
        return len(self.all_imgs)

    def __getitem__(self, idx):
        img_loc = os.path.join(self.main_dir, self.all_imgs[idx])
        image = Image.open(img_loc).convert("RGB")
        tensor_image = self.transform(image)

        img_name = self.all_imgs[idx].replace('.png', '')
        img_df = self.df.loc[self.df['ImageId'] == img_name]

        true_label = img_df['TrueLabel'].item() - 1
        target_label = img_df['TargetClass'].item() - 1

        return tensor_image, true_label


def split_dataset(dataset, test_size=.1, shuffle=True):
    '''
        Split a dataset on train and test set

        Args:
            dataset : the dataset to split
            test_size : the percentage that will correspond to the test set
            shuffle : If you want to shuffle the dataset before splitting it
    '''
    random_seed = 42
    dataset_size = len(dataset)
    
    indices = list(range(dataset_size))
    split = int(np.floor(test_size * dataset_size))
    
    if shuffle:
        np.random.seed(random_seed)
        np.random.shuffle(indices)
    
    return indices[split:], indices[:split]


class NormalizeInverse(object):
    '''
        De-normalizes an image 
        that was normalized with values 'mean' and 'std'
    '''
    def __init__(self, mean, std):
        self.mean = mean
        self.std = std

    def __call__(self, tensor):
        invert_norm = transforms.Normalize(
            mean=[-m_elem/s_elem for m_elem, s_elem in zip(self.mean, self.std)], 
            std=[1/elem for elem in self.std]
        )
        return invert_norm(tensor)

