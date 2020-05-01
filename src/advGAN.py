# modified from https://github.com/mathcbc/advGAN_pytorch/blob/master/advGAN.py


import matplotlib
matplotlib.use('Agg')

import os
import numpy as np
import matplotlib.pyplot as plt

import torch
import torchvision
import torch.nn as nn
import torch.nn.functional as F

import models



models_path = './checkpoints/AdvGAN/'   # path to save models
losses_path = './results/losses/'      # path to save loss plots



def init_weights(m):
    '''
        Custom weights initialization called on G and D
    '''
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        nn.init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        nn.init.normal_(m.weight.data, 1.0, 0.02)
        nn.init.constant_(m.bias.data, 0)

"""
Class to train the AdvGAN
"""
class AdvGAN_Attack:
    def __init__(
                self, 
                device, 
                model, 
                n_labels, 
                n_channels, 
                target, 
                lr, 
                l_inf_bound, 
                alpha, 
                beta, 
                gamma, 
                kappa, 
                c, 
                n_steps_D, 
                n_steps_G, 
                is_relativistic
            ):
        self.device = device
        self.n_labels = n_labels        # number of labels of the target model
        self.model = model      # target model
        
        self.target = target    # target dataset name

        self.lr = lr    # learning rate

        self.l_inf_bound = l_inf_bound      # petrubation bound

        self.alpha = alpha  # weight for GAN loss
        self.beta = beta    # weight for hinge loss
        self.gamma = gamma  # weight for adv loss
        self.kappa = kappa  # Used in Adv loss
        self.c = c  # used in hinge_loss

        self.n_steps_D = n_steps_D     # number of steps to train the discriminator per batch
        self.n_steps_G = n_steps_G      # number of steps to train the generator per batch

        self.is_relativistic = is_relativistic

        self.G = models.Generator(n_channels, n_channels, target).to(device)
        self.D = models.Discriminator(n_channels).to(device)

        # initialize all weights
        self.G.apply(init_weights)
        self.D.apply(init_weights)

        # initialize optimizers
        self.optimizer_G = torch.optim.Adam(self.G.parameters(), lr=self.lr)
        self.optimizer_D = torch.optim.Adam(self.D.parameters(), lr=self.lr)

        # create model save path if it doesn't exist
        if not os.path.exists(models_path):
            os.makedirs(models_path)

        # create loss plot save path if it doesn't exist
        if not os.path.exists('{}{}/'.format(losses_path, target)):
            os.makedirs('{}{}/'.format(losses_path, target))

    """
    Helper function to help train function
    Params :
        x : images
        labels : labels (helps in the adversarial loss)
    Returns :
        loss_D : Discriminator loss
        loss_G : Generator loss
        loss_G_gan : Generator GAN loss
        loss_hinge : Hinge loss
        loss_adv : Carlini & Wagner adversarial loss
    """
    def train_batch(self, x, labels):
        # optimize D
        for i in range(self.n_steps_D):
            perturbation = self.G(x)

            adv_images = torch.clamp(perturbation, -self.l_inf_bound, self.l_inf_bound) + x # clamp peturbation
            adv_images = torch.clamp(adv_images, 0, 1)  # clamp the image itself

            self.D.zero_grad()
            
            logits_real, pred_real = self.D(x)
            logits_fake, pred_fake = self.D(adv_images.detach())

            real = torch.ones_like(pred_real, device=self.device)
            fake = torch.zeros_like(pred_fake, device=self.device)



            if self.is_relativistic:    # apply relatavisitc losses
                # loss_D = F.binary_cross_entropy_with_logits(torch.squeeze(logits_real - logits_fake), real)
                loss_D_real = torch.mean((logits_real - torch.mean(logits_fake) - real)**2)
                loss_D_fake = torch.mean((logits_fake - torch.mean(logits_real) + real)**2)

                loss_D = (loss_D_fake + loss_D_real) / 2
            else:       # apply LSGAN losses
                loss_D_real = F.mse_loss(pred_real, torch.ones_like(pred_real, device=self.device))
                loss_D_fake = F.mse_loss(pred_fake, torch.zeros_like(pred_fake, device=self.device))
                loss_D = loss_D_fake + loss_D_real

            loss_D.backward()
            self.optimizer_D.step()

        # optimize G
        for i in range(self.n_steps_G):
            self.G.zero_grad()

            # the Hinge Loss part of L
            perturbation_norm = torch.mean(torch.norm(perturbation.view(perturbation.shape[0], -1), 2, dim=1))
            loss_hinge = torch.max(torch.zeros(1, device=self.device), perturbation_norm - self.c)

            # the Adv Loss part of L
            logits_model = self.model(adv_images)
            probs_model = F.softmax(logits_model, dim=1)
            onehot_labels = torch.eye(self.n_labels, device=self.device)[labels]

            # C&W loss
            real_class_prob = torch.sum(onehot_labels * probs_model, dim=1)
            target_class_prob, _ = torch.max((1 - onehot_labels) * probs_model - onehot_labels * 10000, dim=1)
            loss_adv = torch.max(real_class_prob - target_class_prob, self.kappa * torch.ones_like(target_class_prob))
            loss_adv = torch.sum(loss_adv)

            # the GAN Loss part of L
            logits_real, pred_real = self.D(x)
            logits_fake, pred_fake = self.D(adv_images)

            if self.is_relativistic:    # apply relatavisitc losses
                # loss_G_gan = F.binary_cross_entropy_with_logits(torch.squeeze(logits_fake - logits_real), real)
                loss_G_real = torch.mean((logits_real - torch.mean(logits_fake) + real)**2)
                loss_G_fake = torch.mean((logits_fake - torch.mean(logits_real) - real)**2)
                
                loss_G_gan = (loss_G_real + loss_G_fake) / 2
            else:   # apply LSGAN loss
                loss_G_gan = F.mse_loss(pred_fake, torch.ones_like(pred_fake, device=self.device))


            loss_G = self.gamma * loss_adv + self.alpha * loss_G_gan + self.beta * loss_hinge
            loss_G.backward()
            self.optimizer_G.step()

        return loss_D.item(), loss_G.item(), loss_G_gan.item(), loss_hinge.item(), loss_adv.item()

    """
    Function to train the GAN
    Params :
        train_dataloader : pytorch data loader
        epochs : number of epochs to train for
    """
    def train(self, train_dataloader, epochs):
        loss_D, loss_G, loss_G_gan, loss_hinge, loss_adv = [], [], [], [], []
        
        for epoch in range(1, epochs+1):
            loss_D_sum, loss_G_sum, loss_G_gan_sum, loss_hinge_sum, loss_adv_sum = 0, 0, 0, 0, 0
            for i, data in enumerate(train_dataloader, start=0):
                images, labels = data
                images, labels = images.to(self.device), labels.to(self.device)

                loss_D_batch, loss_G_batch, loss_G_fake_batch, loss_hinge_batch, loss_adv_batch = self.train_batch(images, labels)

                loss_D_sum += loss_D_batch
                loss_G_sum += loss_G_batch
                loss_adv_sum += loss_adv_batch
                loss_G_gan_sum += loss_G_fake_batch
                loss_hinge_sum += loss_hinge_batch

            # print statistics
            batch_size = len(train_dataloader)
            print('Epoch {}: \nLoss D: {}, \nLoss G: {}, \n\t-Loss Adv: {}, \n\t-Loss G GAN: {}, \n\t-Loss Hinge: {}, \n'.format(
                epoch, 
                loss_D_sum / batch_size, 
                loss_G_sum / batch_size, 
                loss_adv_sum / batch_size, 
                loss_G_gan_sum / batch_size,
                loss_hinge_sum / batch_size, 
            ))

            loss_D.append(loss_D_sum / batch_size)
            loss_G.append(loss_G_sum / batch_size)
            loss_adv.append(loss_adv_sum / batch_size)
            loss_G_gan.append(loss_G_gan_sum / batch_size)
            loss_hinge.append(loss_hinge_sum / batch_size)

            # save generator
            torch.save(self.G.state_dict(), '{}G_epoch_{}.pth'.format(models_path, str(epoch)))

        # Discriminator loss
        plt.figure()
        plt.plot(loss_D)
        plt.savefig(losses_path + self.target + '/loss_D.png')

        # Generator loss
        plt.figure()
        plt.plot(loss_G)
        plt.savefig(losses_path + self.target + '/loss_G.png')

        # Adversarial loss
        plt.figure()
        plt.plot(loss_adv)
        plt.savefig(losses_path + self.target + '/loss_adv.png')

        # Gan loss
        plt.figure()
        plt.plot(loss_G_gan)
        plt.savefig(losses_path + self.target + '/loss_G_gan.png')

        # Hinge loss
        plt.figure()
        plt.plot(loss_hinge)
        plt.savefig(losses_path + self.target + '/loss_hinge.png')



