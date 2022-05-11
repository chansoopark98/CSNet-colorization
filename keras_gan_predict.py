from model.model_builder import build_dis, build_gen
import tensorflow as tf
from tensorflow.keras.layers import Input, concatenate
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.losses import binary_crossentropy, mean_absolute_error
from tensorflow.keras.mixed_precision import experimental as mixed_precision
import tensorflow.keras.backend as K
from tqdm import tqdm
import tensorflow_datasets as tfds
import matplotlib.pyplot as plt
import os
import tensorflow_io as tfio
import numpy as np

def eacc(y_true, y_pred):
    return K.mean(K.equal(K.round(y_true), K.round(y_pred)))

def l1(y_true, y_pred):
    return K.mean(K.abs(y_pred - y_true))

def create_model_gen(input_shape, output_channels):
    model_input, model_output = build_gen(image_size=input_shape, output_channels=output_channels)

    model = tf.keras.Model(model_input, model_output)
    return model

def create_model_dis(input_shape):
    model_input, model_output = build_dis(image_size=input_shape)

    model = tf.keras.Model(model_input, model_output)
    return model

def create_model_gan(input_shape, generator, discriminator):
    input = Input(input_shape)

    gen_out = generator(input)
    gen_out = concatenate([input, gen_out], axis=3)
    dis_out = discriminator(gen_out)
    # dis_out = discriminator(gen_out)

    model = tf.keras.Model(inputs=[input], outputs=[dis_out, gen_out], name='dcgan')
    return model

def create_models(input_shape_gen, input_shape_dis, output_channels, lr, momentum, loss_weights):
    optimizer = Adam(lr=lr, beta_1=momentum)
    optimizer = mixed_precision.LossScaleOptimizer(optimizer, loss_scale='dynamic')  # tf2.4.1 이전

    model_gen = create_model_gen(input_shape=input_shape_gen, output_channels=output_channels)
    model_gen.compile(loss=mean_absolute_error, optimizer=optimizer)

    model_dis = create_model_dis(input_shape=input_shape_dis)
    model_dis.trainable = False

    model_gan = create_model_gan(input_shape=input_shape_gen, generator=model_gen, discriminator=model_dis)
    model_gan.compile(
        loss=[binary_crossentropy, l1],
        metrics=[eacc, 'accuracy'],
        loss_weights=loss_weights,
        optimizer=optimizer
    )

    model_dis.trainable = True
    model_dis.compile(loss=binary_crossentropy, optimizer=optimizer)

    return model_gen, model_dis, model_gan

def demo_prepare(path):
    img = tf.io.read_file(path)
    img = tf.image.decode_image(img, channels=3)
    img = tf.image.resize_with_pad(img, 512, 512)
    return (img)

if __name__ == '__main__':
    EPOCHS = 200
    BATCH_SIZE = 1
    LEARNING_RATE = 0.0005
    MOMENTUM = 0.5
    LAMBDA1 = 1
    LAMBDA2 = 100
    INPUT_SHAPE_GEN = (512, 512, 1)
    INPUT_SHAPE_DIS = (512, 512, 3)
    GEN_OUTPUT_CHANNEL = 2
    DATASET_DIR ='./datasets'
    WEIGHTS_GEN = './checkpoints/0510/GEN512_19.h5'
    WEIGHTS_DIS = './checkpoints/0510/DIS512_19.h5'
    WEIGHTS_GAN = './checkpoints/0510/GAN512_19.h5'

    model_gen, model_dis, model_gan = create_models(
        input_shape_gen=INPUT_SHAPE_GEN,
        input_shape_dis=INPUT_SHAPE_DIS,
        output_channels=GEN_OUTPUT_CHANNEL,
        lr=LEARNING_RATE,
        momentum=MOMENTUM,
        loss_weights=[LAMBDA1, LAMBDA2])

    model_gen.load_weights('./checkpoints/0510/GEN512_19.h5', by_name=True)
    train_data = tfds.load('CustomCeleba',
                           data_dir=DATASET_DIR, split='train[:1%]', shuffle_files=True)
    number_train = train_data.reduce(0, lambda x, _: x + 1).numpy()
    print("학습 데이터 개수", number_train)
    steps_per_epoch = number_train // BATCH_SIZE
    train_data = train_data.shuffle(1024)
    train_data = train_data.padded_batch(BATCH_SIZE)
    # train_data = train_data.repeat(EPOCHS)
    train_data = train_data.prefetch(tf.data.experimental.AUTOTUNE)

    save_path = './checkpoints/results/' + 'gan' + '/'
    os.makedirs(save_path, exist_ok=True)
    batch_index = 0

    filenames = os.listdir('./demo_images')
    filenames.sort()
    demo_imgs = tf.data.Dataset.list_files('./demo_images/' + '*', shuffle=False)
    demo_test = demo_imgs.map(demo_prepare)
    demo_test = demo_test.batch(BATCH_SIZE)
    demo_steps = len(filenames) // BATCH_SIZE
    demo = False
    demo_path = './demo_outputs/' + 'demo/'
    os.makedirs(demo_path, exist_ok=True)

    if demo:
        dataset = demo_test
        steps = demo_steps
    else:
        dataset = train_data
        steps = steps_per_epoch

    pbar = tqdm(dataset, total=steps, desc='Batch', leave=True, disable=False)

    l_cent = 50.
    l_norm = 100.
    ab_norm = 110.

    for features in pbar:
        if demo:
            img = features
        else:
            img = tf.cast(features['image'], tf.uint8)
        shape = img.shape
        
        img = tf.image.resize(img, (INPUT_SHAPE_GEN[0], INPUT_SHAPE_GEN[1]), tf.image.ResizeMethod.BILINEAR)

        img = tf.cast(img, tf.float32)  # if use ycbcr
        img /= 255.  # TODO! if use lab

        lab = tfio.experimental.color.rgb_to_lab(img)
        
        l_channel = lab[:, :, :, 0]
        l_channel = (l_channel - l_cent) / l_norm

        a = lab[:, :, :, 1]
        a = a / ab_norm

        b = lab[:, :, :, 2]
        b = b / ab_norm

        l_channel = tf.expand_dims(l_channel, axis=-1)
        a = tf.expand_dims(a, axis=-1)
        b = tf.expand_dims(b, axis=-1)

        ab = tf.concat([a, b], axis=-1)
        norm_lab = tf.concat([l_channel, ab], axis=-1)

        pred_ab = model_gen.predict(l_channel)

        for i in range(len(pred_ab)):
            batch_l = l_channel[i]
            batch_l = batch_l * l_norm + l_cent


            batch_a = pred_ab[i][:, :, 0]
            batch_a = batch_a * ab_norm
            batch_a = tf.expand_dims(batch_a, -1)

            batch_b = pred_ab[i][:, :, 1]
            batch_b = batch_b * ab_norm
            batch_b = tf.expand_dims(batch_b, -1)


            pred_lab = tf.concat([batch_l, batch_a, batch_b], axis=-1)

            pred_lab = tfio.experimental.color.lab_to_rgb(pred_lab)
            
            
            rows = 1
            cols = 2
            fig = plt.figure()

            ax0 = fig.add_subplot(rows, cols, 1)
            ax0.imshow(pred_lab)
            ax0.set_title('Prediction')
            ax0.axis("off")

            ax1 = fig.add_subplot(rows, cols, 2)
            ax1.imshow(img[i])
            ax1.set_title('Groundtruth')
            ax1.axis("off")

            if demo:
                plt.savefig(demo_path + str(batch_index) + 'output.png', dpi=300)
            else:
                plt.savefig(save_path + str(batch_index) + 'output.png', dpi=300)
            # pred = tf.cast(pred, tf.int32)
            # plt.show()
            # tf.keras.preprocessing.image.save_img(save_path + str(batch_index) + '_1_input.jpg', output)
            # tf.keras.preprocessing.image.save_img(save_path + str(batch_index) + '_2_gt.jpg', img[0])
            # tf.keras.preprocessing.image.save_img(save_path + str(batch_index) + '_3_out.jpg', pred)

            batch_index += 1
