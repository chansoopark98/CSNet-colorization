# from __future__ import print_function, division
from tensorflow.keras.layers import Input, Dense,  Flatten, Dropout, UpSampling2D, Conv2D
from tensorflow.keras.layers import BatchNormalization, Activation, ZeroPadding2D, LeakyReLU, MaxPooling2D
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import backend as K
from tensorflow.keras.mixed_precision import experimental as mixed_precision
import tensorflow_io as tfio
import tensorflow as tf
import matplotlib.pyplot as plt
from tqdm import tqdm
import numpy as np
import tensorflow_datasets as tfds

from utils.datasets import Dataset
from model.model_builder import base_model
from model.model import Conv3x3

BATCH_SIZE = 8
EPOCHS = 50
DATASET_DIR = './datasets/'
IMAGE_SIZE = (512, 512)
num_classes = 2

def l1(y_true, y_pred):
    return K.mean(K.abs(y_pred - y_true))

class GAN():
    def __init__(self):
        self.img_rows = 512
        self.img_cols = 512
        self.channels = 2
        self.img_shape = (self.img_rows, self.img_cols, self.channels)
        self.latent_dim = 100


        optimizer = Adam(0.0002, 0.5)
        optimizer = mixed_precision.LossScaleOptimizer(optimizer, loss_scale='dynamic')  # tf2.4.1 이전

        # self.options = tf.data.Options()
        # self.options.experimental_distribute.auto_shard_policy = tf.data.experimental.AutoShardPolicy.OFF

        # self.train_dataset_config = Dataset(DATASET_DIR, IMAGE_SIZE, BATCH_SIZE, mode='train',
        #                                dataset='CustomCelebahq')
        # self.train_data = self.train_dataset_config.gan_trainData(self.train_dataset_config.train_data)
        self.train_data = tfds.load('CustomCelebahq',
                               data_dir=DATASET_DIR, split='train[:25%]')
        self.number_train = self.train_data.reduce(0, lambda x, _: x + 1).numpy()
        print("학습 데이터 개수", self.number_train)
        self.train_data = self.train_data.shuffle(1024)
        self.train_data = self.train_data.batch(BATCH_SIZE)
        # self.train_data = self.train_data.prefetch(tf.data.experimental.AUTOTUNE)
        # self.train_data = self.train_data.repeat()

        # self.train_data = self.train_data.with_options(self.options)
        # self.train_data = mirrored_strategy.experimental_distribute_dataset(self.train_data)
        # options = tf.data.Options()
        # options.experimental_distribute.auto_shard_policy = tf.data.experimental.AutoShardPolicy.DATA
        # self.train_data = self.train_data.with_options(options)

        self.steps_per_epoch = self.number_train // BATCH_SIZE


        # Build and compile the discriminator
        self.discriminator = self.build_discriminator()
        self.discriminator.compile(loss='binary_crossentropy',
            optimizer=optimizer,
            metrics=['accuracy'])

        # Build the generator
        self.generator = self.build_generator()

        # The generator takes noise as input and generates imgs
        z = Input(shape=(512, 512, 1))
        img = self.generator(z)

        # For the combined model we will only train the generator
        self.discriminator.trainable = False

        # The discriminator takes generated images as input and determines validity
        validity = self.discriminator(img)

        # The combined model  (stacked generator and discriminator)
        # Trains the generator to fool the discriminator
        self.combined = Model(z, validity)
        self.combined.compile(loss='mse', optimizer=optimizer)

    def build_generator(self):

        model_input, model_output = base_model(image_size=(512, 512, 1), num_classes=2)
        model = tf.keras.Model(model_input, model_output)
        return model

    def build_discriminator(self):

        inputs = Input(shape=(512, 512, 2))
        x = Conv3x3(inputs, channel=64, rate=1, activation='relu')
        x = MaxPooling2D()(x)
        x = Conv3x3(x, channel=128, rate=1, activation='relu')
        x = MaxPooling2D()(x)
        x = Conv3x3(x, channel=256, rate=1, activation='relu')
        x = MaxPooling2D()(x)
        x = Conv3x3(x, channel=512, rate=1, activation='relu')
        x = MaxPooling2D()(x)
        x = Conv3x3(x, channel=512, rate=1, activation='relu')

        x = Flatten()(x)
        x = Dense(1, activation='sigmoid')(x)

        model = Model(inputs=inputs, outputs=x, name='discriminator')

        return model

    def train(self, epochs, batch_size=128, sample_interval=50):

        pbar = tqdm(self.train_data, total=self.steps_per_epoch, desc = 'Batch', leave = True, disable=False)
        for epoch in range(epochs):
            # for features in tqdm(self.train_data, total=self.steps_per_epoch):
            for features in pbar:
            # for features in self.train_data:
                # ---------------------
                #  Train Discriminator
                # ---------------------
                img = tf.cast(features['image'], tf.uint8)
                shape = img.shape
                # Adversarial ground truths
                valid = np.ones((shape[0], 1))
                fake = np.zeros((shape[0], 1))

                img = tf.image.resize(img, (512, 512), tf.image.ResizeMethod.NEAREST_NEIGHBOR)
                # gray_img = tfio.experimental.color.rgb_to_grayscale(img)

                # gray_img = tf.image.rgb_to_grayscale(img)
                #
                # Gray_3channel = tf.concat([gray_img, gray_img, gray_img], axis=-1)
                # gray_ycbcr = tfio.experimental.color.rgb_to_ycbcr(Gray_3channel)
                # gray_Y = gray_ycbcr[:, :, 0]
                # gray_Y = tf.cast(gray_Y, tf.float32)
                # gray_Y = (gray_Y / 127.5) - 1.0
                # gray_Y = tf.expand_dims(gray_Y, axis=-1)

                img_YCbCr = tfio.experimental.color.rgb_to_ycbcr(img)
                gray_Y = img_YCbCr[:, :, :, 0]
                gray_Y = tf.cast(gray_Y, tf.float32)
                gray_Y = (gray_Y / 127.5) - 1.0
                # gray_Y /= 255.
                gray_Y = tf.expand_dims(gray_Y, axis=-1)

                Cb = img_YCbCr[:, :, :, 1]
                Cb = tf.cast(Cb, tf.float32)
                Cb = (Cb / 127.5) - 1.0
                # Cb /= 255.
                Cb = tf.expand_dims(Cb, axis=-1)

                Cr = img_YCbCr[:, :, :, 2]
                Cr = tf.cast(Cr, tf.float32)
                Cr = (Cr / 127.5) - 1.0
                # Cr /= 255.
                Cr = tf.expand_dims(Cr, axis=-1)

                CbCr = tf.concat([Cb, Cr], axis=-1)


                # Generate a batch of new images


                noise = tf.random.uniform(shape=[batch_size, 512, 512, 1], maxval=1.0)
                gen_imgs = self.generator.predict(gray_Y)

                # Train the discriminator
                d_loss_real = self.discriminator.train_on_batch(CbCr, valid)
                d_loss_fake = self.discriminator.train_on_batch(gen_imgs, fake)
                d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)

                # ---------------------
                #  Train Generator
                # ---------------------

                # noise = np.random.normal(0, 1, (batch_size, self.latent_dim))

                # Train the generator (to have the discriminator label samples as valid)
                noise = tf.random.uniform(shape=[batch_size, 512, 512, 1], maxval=1.0)
                g_loss = self.combined.train_on_batch(noise, valid)

                # Plot the progress
                # t.set_description("text", refresh=True)

                # print("%d [D loss: %f, acc.: %.2f%%] [G loss: %f]" % (
                # epoch, self.d_loss[0], 100 * self.d_loss[1], self.g_loss))

                pbar.set_description("%d [D loss: %f, acc.: %.2f%%] [G loss: %f]" % (
                epoch, d_loss[0], 100 * d_loss[1], g_loss))

            # self.train_data = self.train_data.repeat()


            # If at save interval => save generated image samples
            if epoch % sample_interval == 0:
                self.sample_images(epoch)

    def sample_images(self, epoch):
        # r, c = 5, 5
        # noise = np.random.normal(0, 1, (r * c, self.latent_dim))
        # gen_imgs = self.generator.predict(noise)
        #
        # # Rescale images 0 - 1
        # gen_imgs = 0.5 * gen_imgs + 0.5
        #
        # fig, axs = plt.subplots(r, c)
        # cnt = 0
        # for i in range(r):
        #     for j in range(c):
        #         axs[i,j].imshow(gen_imgs[cnt, :,:,0], cmap='gray')
        #         axs[i,j].axis('off')
        #         cnt += 1
        # fig.savefig("images/%d.png" % epoch)
        # plt.close()
        self.combined.save_weights('test_model.h5')
        # self.combined.s


if __name__ == '__main__':
    # mirrored_strategy = tf.distribute.MirroredStrategy()
    # with mirrored_strategy.scope():
    gan = GAN()
    gan.train(epochs=EPOCHS, batch_size=BATCH_SIZE, sample_interval=1)