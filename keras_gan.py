from model.model_builder import build_dis, build_gen
import tensorflow as tf
from tensorflow.keras.layers import Input, concatenate
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.losses import binary_crossentropy, mean_absolute_error
from tensorflow.keras.mixed_precision import experimental as mixed_precision
import tensorflow.keras.backend as K
from tqdm import tqdm
import tensorflow_datasets as tfds


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
    dis_out = discriminator(concatenate([gen_out, input], axis=3))

    model = tf.keras.Model(inputs=[input], outputs=[dis_out, gen_out], name='dcgan')
    return model

def create_models(input_shape_gen, input_shape_dis, output_channels, lr, momentum, loss_weights):

    optimizer = Adam(learning_rate=lr, beta_1=momentum)
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

if __name__ == '__main__':
    EPOCHS = 200
    BATCH_SIZE = 32
    # LEARNING_RATE = 0.0005
    LEARNING_RATE = 0.0002
    MOMENTUM = 0.5
    LAMBDA1 = 1
    LAMBDA2 = 100
    INPUT_SHAPE_GEN = (256, 256, 1)
    INPUT_SHAPE_DIS = (256, 256, 3)
    GEN_OUTPUT_CHANNEL = 2
    DATASET_DIR ='./datasets'
    WEIGHTS_GEN = './checkpoints/YUV_GAN_Gen.h5'
    WEIGHTS_DIS = './checkpoints/YUV_GAN_Dis.h5'
    WEIGHTS_GAN = './checkpoints/YUV_GAN_Gan.h5'

    model_gen, model_dis, model_gan = create_models(
        input_shape_gen=INPUT_SHAPE_GEN,
        input_shape_dis=INPUT_SHAPE_DIS,
        output_channels=GEN_OUTPUT_CHANNEL,
        lr=LEARNING_RATE,
        momentum=MOMENTUM,
        loss_weights=[LAMBDA1, LAMBDA2])

    train_data = tfds.load('CustomCelebahq',
                           data_dir=DATASET_DIR, split='train', shuffle_files=True)

    number_train = train_data.reduce(0, lambda x, _: x + 1).numpy()
    print("학습 데이터 개수", number_train)
    steps_per_epoch = number_train // BATCH_SIZE
    train_data = train_data.shuffle(1024)
    train_data = train_data.padded_batch(BATCH_SIZE)
    # train_data = train_data.repeat(EPOCHS)
    train_data = train_data.prefetch(tf.data.experimental.AUTOTUNE)


    for epoch in range(EPOCHS):
        pbar = tqdm(train_data, total=steps_per_epoch, desc='Batch', leave=True, disable=False)
        batch_counter = 0
        toggle = True
        dis_res = 0
        for features in pbar:
            batch_counter += 1
            # ---------------------
            #  Train Discriminator
            # ---------------------
            img = tf.cast(features['image'], tf.uint8)
            shape = img.shape

            img = tf.cast(img, tf.uint8)
            img = tf.image.resize(img, (INPUT_SHAPE_GEN[0], INPUT_SHAPE_GEN[1]), tf.image.ResizeMethod.BICUBIC)

            # data augmentation
            if tf.random.uniform([], minval=0, maxval=1) > 0.5:
                img = tf.image.flip_left_right(img)
            if tf.random.uniform([], minval=0, maxval=1) > 0.5:
                h, w, _ = img.shape
                scale = tf.random.uniform([], 0.7, 1.1)
                nh = h * scale
                nw = w * scale
                img = tf.image.resize(img, (nh, nw), method=tf.image.ResizeMethod.BICUBIC)
                img = tf.image.resize_with_crop_or_pad(img, h, w)

            img /= 255
            img = tf.cast(img, tf.float32)
            yuv = tf.image.rgb_to_yuv(img)

            y = yuv[:, :, :, 0]
            y = tf.cast(y, tf.float32)
            y *= 255.
            # y = (y / 127.5) - 1.0
            y /= 255.
            y = tf.expand_dims(y, axis=-1)

            u = yuv[:, :, :, 1]
            u = tf.cast(u, tf.float32)
            u = (u + 0.5) * 255.
            # u = (u / 127.5) - 1.0
            u /= 255.
            u = tf.expand_dims(u, axis=-1)

            v = yuv[:, :, :, 2]
            v = tf.cast(v, tf.float32)
            v = (v + 0.5) * 255.
            # v = (v / 127.5) - 1.0
            v /= 255.
            v = tf.expand_dims(v, axis=-1)

            uv = tf.concat([u, v], axis=-1)

            if batch_counter % 2 == 0:
                toggle = not toggle
                if toggle:
                    x_dis = tf.concat((model_gen.predict(y), y), axis=3)
                    y_dis = tf.zeros((shape[0], 1)) # TODO: np to tf
                else:
                    x_dis = tf.concat((uv, y), axis=3)
                    y_dis = tf.ones((shape[0], 1))
                    y_dis = tf.ones((shape[0], 1)) * 0.9
                    # y_dis = np.random.uniform(low=0.9, high=1, size=BATCH_SIZE)


                dis_res = model_dis.train_on_batch(x_dis, y_dis)

            model_dis.trainable = False
            x_gen = y
            y_gen = tf.ones((shape[0], 1))
            x_output = uv
            gan_res = model_gan.train_on_batch(x_gen, [y_gen, x_output])
            model_dis.trainable = True

            pbar.set_description("Epoch : %d Dis loss: %f Gan total: %f Gan loss: %f Gan L1: %f P_ACC: %f ACC: %f" % (epoch, dis_res,
                                    gan_res[0], gan_res[1], gan_res[2], gan_res[5], gan_res[6]))

        model_gen.save_weights(WEIGHTS_GEN, overwrite=True)
        model_dis.save_weights(WEIGHTS_DIS, overwrite=True)
        model_gan.save_weights(WEIGHTS_GAN, overwrite=True)
