import os
import torch
import numpy as np
from torch import optim
from models import BaseVAE
from models.types_ import *
import pytorch_lightning as pl
import torchvision.utils as vutils
import matplotlib.pyplot as plt
from sklearn.manifold import TSNE
from random import randint
from torchvision import transforms


class VAEXperiment(pl.LightningModule):

    def __init__(self,
                 vae_model: BaseVAE,
                 params: dict) -> None:
        super(VAEXperiment, self).__init__()

        self.model = vae_model
        self.params = params
        self.curr_device = None
        self.hold_graph = False
        try:
            self.hold_graph = self.params['retain_first_backpass']
        except:
            pass

    def forward(self, input: Tensor, **kwargs) -> Tensor:
        return self.model(input, **kwargs)

    def training_step(self, batch, batch_idx, optimizer_idx = 0):
        real_img, labels = batch
        self.curr_device = real_img.device

        results = self.forward(real_img, labels = labels)
        train_loss = self.model.loss_function(*results,
                                              M_N = self.params['kld_weight'], #al_img.shape[0]/ self.num_train_imgs,
                                              optimizer_idx=optimizer_idx,
                                              batch_idx = batch_idx)
        self.log_dict({key: val.item() for key, val in train_loss.items()}, sync_dist=True)

        return train_loss['loss']

    def validation_step(self, batch, batch_idx, optimizer_idx = 0):
        real_img, labels = batch
        self.curr_device = real_img.device

        results = self.forward(real_img, labels = labels)
        val_loss = self.model.loss_function(*results,
                                            M_N = 1, #real_img.shape[0]/ self.num_val_imgs,
                                            optimizer_idx = optimizer_idx,
                                            batch_idx = batch_idx)
        
        self.log_dict({f"val_{key}": val.item() for key, val in val_loss.items()}, sync_dist=True)

        
    def on_validation_end(self) -> None:
        self.save_model()
        self.sample_images()
    
    def save_model(self):
        path = os.path.join(self.logger.log_dir , "Model", "state_dict_model.pt") 
        torch.save(self.model.state_dict(), path)
    
    def sample_image(self):
        sample = self.model.sample(1, self.curr_device)
        plt.imshow(sample.detach().cpu().numpy().reshape(64,64), cmap='gray')
        plt.show()
        
    # Visualisation de l'effet de chaque dimension sur un point aléatoire dans espace latent
    def visualize_each_dim_random(self, latent_dim, num_samples=20):
        # Générer un échantillon aléatoire dans l'espace latent
        latent_sample = torch.randn(1, latent_dim).to(self.curr_device)

        # Générer des échantillons en modifiant sélectivement chaque dimension de l'espace latent
        for i in range(latent_dim):
            latent_copy = latent_sample.clone()
            values = torch.linspace(-2,2, num_samples)
            for j in range(num_samples):
                latent_copy[0, i] = values[j]
                generated_sample = self.model.decode(latent_copy)
                plt.subplot(latent_dim, num_samples, (i*num_samples) + j + 1)
                plt.imshow(generated_sample.detach().cpu().numpy().reshape(64,64), cmap='gray')
                plt.axis('off')
        plt.show()

    # Visualisation de l'effet de chaque dimension sur chaque chiffre
    def visualize_each_dim_all_numbers(self, data, latent_dim):
        encoded_data = []
        for img in data:
            encoded_data.append(self.model.encode(torch.reshape(img,(1,1,64,64)))[0])
        plt.figure(figsize=(15, 2))
        for i in range(latent_dim):
            for k,img in enumerate(encoded_data):
                latent_copy = img.clone()
                values = torch.linspace(-2, 2, 20)
                for j in range(20):
                    latent_copy[0, i] = values[j]
                    generated_sample = self.model.decode(latent_copy)
                    plt.subplot(10, 20, (k*20)+j + 1)
                    plt.imshow(generated_sample.detach().cpu().numpy().reshape(64,64), cmap='gray')
                    plt.axis('off')
            plt.suptitle(f"Variation de la dimension {i + 1}")
            plt.show()

    # Affichage d'un exemple de reconstruction et de génération aléatoire
    def recons_and_gen(self, data, latent_dim):
        imgs = []
        k = 1
        # Récupération d'image aléatoire dans le dataset
        for i in range(10):
            r = randint(0, len(data))
            plt.subplot(10, 2, k)
            k += 2
            img = data[r][0]
            imgs.append(img)
            plt.imshow(img.detach().cpu().numpy().reshape(64,64), cmap='gray')
            plt.axis('off')
        # Encodage de ces images par le modèle
        k = 2
        for img in imgs:
            plt.subplot(10, 2, k)
            k += 2
            plt.imshow(self.model.generate(torch.reshape(img,(1,1,64,64))).detach().cpu().numpy().reshape(64,64), cmap='gray')
            plt.axis('off')
        plt.suptitle("Reconstruction")
        plt.show()

        # Génération de 20 images par le modèle avec des points aléatoire de l'espace latent
        latent_samples = torch.randn(20, latent_dim).to(self.curr_device)
        for j in range(20):
            generated_sample = self.model.decode(latent_samples[j])
            plt.subplot(10, 2, j+1)
            plt.imshow(generated_sample.detach().cpu().numpy().reshape(64,64), cmap='gray')
            plt.axis('off')
        plt.suptitle("Génération à partir de point random")
        plt.show()

    #voir l'espace latent
    def visualize_latent_space(self, valid_loader):
        points = []
        label_idcs = []
        # Encodage du dataset par le modèle
        for i, data in enumerate(valid_loader):
            img, label = [d.to(self.curr_device) for d in data]
            proj = self.model.encode(img)
            points.extend(proj[0].detach().cpu().numpy())
            label_idcs.extend(label.detach().cpu().numpy())
            del img, label
        points = np.array(points)
        # Réduction de dimensions pour afficher par la suite
        point_embedded = TSNE(n_components=2).fit_transform(points)
        
        # Création du plot
        fig, ax = plt.subplots(figsize=(10, 10))
        scatter = ax.scatter(x=point_embedded[:, 0], y=point_embedded[:, 1], s=2.0, c=label_idcs, cmap='tab10', alpha=0.9, zorder=2)
        classes = np.unique(label_idcs)
        legend_labels = [f'{cls}' for cls in classes]
        legend = ax.legend(handles=scatter.legend_elements()[0], labels=legend_labels, title='Classes', loc='upper left')
        ax.add_artist(legend)
        ax.grid(True, color="lightgray", alpha=1.0, zorder=0)
        plt.show()

    
    def sample_images(self):
        # Get sample reconstruction image            
        test_input, test_label = next(iter(self.trainer.datamodule.test_dataloader()))
        test_input = test_input.to(self.curr_device)
        test_label = test_label.to(self.curr_device)

#         test_input, test_label = batch
        recons = self.model.generate(test_input, labels = test_label)
        vutils.save_image(recons.data,
                          os.path.join(self.logger.log_dir , 
                                       "Reconstructions", 
                                       f"recons_{self.logger.name}_Epoch_{self.current_epoch}.png"),
                          normalize=True,
                          nrow=12)

        try:
            samples = self.model.sample(144,
                                        self.curr_device,
                                        labels = test_label)
            vutils.save_image(samples.cpu().data,
                              os.path.join(self.logger.log_dir , 
                                           "Samples",      
                                           f"{self.logger.name}_Epoch_{self.current_epoch}.png"),
                              normalize=True,
                              nrow=12)
        except Warning:
            pass

    def configure_optimizers(self):

        optims = []
        scheds = []

        optimizer = optim.Adam(self.model.parameters(),
                               lr=self.params['LR'],
                               weight_decay=self.params['weight_decay'])
        optims.append(optimizer)
        # Check if more than 1 optimizer is required (Used for adversarial training)
        try:
            if self.params['LR_2'] is not None:
                optimizer2 = optim.Adam(getattr(self.model,self.params['submodel']).parameters(),
                                        lr=self.params['LR_2'])
                optims.append(optimizer2)
        except:
            pass

        try:
            if self.params['scheduler_gamma'] is not None:
                scheduler = optim.lr_scheduler.ExponentialLR(optims[0],
                                                             gamma = self.params['scheduler_gamma'])
                scheds.append(scheduler)

                # Check if another scheduler is required for the second optimizer
                try:
                    if self.params['scheduler_gamma_2'] is not None:
                        scheduler2 = optim.lr_scheduler.ExponentialLR(optims[1],
                                                                      gamma = self.params['scheduler_gamma_2'])
                        scheds.append(scheduler2)
                except:
                    pass
                return optims, scheds
        except:
            return optims
