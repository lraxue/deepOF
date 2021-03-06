import tensorflow as tf
import tensorflow.contrib.slim as slim
from tensorflow.contrib.layers.python.layers import initializers
from tensorflow.python.ops import init_ops
import numpy as np

def VGG16(photo_source, photo_target, geo_source, geo_target, loss_weight):
    
    # Add local response normalization (ACROSS_CHANNELS) for computing photometric loss
    inputs_norm = tf.nn.local_response_normalization(geo_source, depth_radius=4, beta=0.7)
    outputs_norm = tf.nn.local_response_normalization(geo_target, depth_radius=4, beta=0.7)

    with slim.arg_scope([slim.conv2d, slim.conv2d_transpose], 
                        weights_initializer=initializers.xavier_initializer(),
                        weights_regularizer=None,
                        biases_initializer=init_ops.zeros_initializer,
                        biases_regularizer=None,
                        activation_fn=tf.nn.elu):       # original use leaky ReLU, now we use elu
        
        conv1_1 = slim.conv2d(tf.concat(3, [photo_source, photo_target]), 64, [3, 3], scope='conv1_1')
        conv1_2 = slim.conv2d(conv1_1, 64, [3, 3], scope='conv1_2')
        pool1 = slim.max_pool2d(conv1_2, [2, 2], scope='pool1')

        conv2_1 = slim.conv2d(pool1, 128, [3, 3], scope='conv2_1')
        conv2_2 = slim.conv2d(conv2_1, 128, [3, 3], scope='conv2_2')
        pool2 = slim.max_pool2d(conv2_2, [2, 2], scope='pool2')

        conv3_1 = slim.conv2d(pool2, 256, [3, 3], scope='conv3_1')
        conv3_2 = slim.conv2d(conv3_1, 256, [3, 3], scope='conv3_2')
        conv3_3 = slim.conv2d(conv3_2, 256, [3, 3], scope='conv3_3')
        pool3 = slim.max_pool2d(conv3_3, [2, 2], scope='pool3')

        conv4_1 = slim.conv2d(pool3, 512, [3, 3], scope='conv4_1')
        conv4_2 = slim.conv2d(conv4_1, 512, [3, 3], scope='conv4_2')
        conv4_3 = slim.conv2d(conv4_2, 512, [3, 3], scope='conv4_3')
        pool4 = slim.max_pool2d(conv4_3, [2, 2], scope='pool4')

        conv5_1 = slim.conv2d(pool4, 512, [3, 3], scope='conv5_1')
        conv5_2 = slim.conv2d(conv5_1, 512, [3, 3], scope='conv5_2')
        conv5_3 = slim.conv2d(conv5_2, 512, [3, 3], scope='conv5_3')
        pool5 = slim.max_pool2d(conv5_3, [2, 2], scope='pool5')
       
        # Hyper-params for computing unsupervised loss
        epsilon = 0.0001 
        alpha_c = 0.25
        alpha_s = 0.37
        lambda_smooth = 1.0
        scale = 2       # for deconvolution
        
        deltaWeights = {}
        # Calculating flow derivatives
        flow_width = tf.constant([[0, 0, 0], [0, 1, -1], [0, 0, 0]], tf.float32)
        flow_width_filter = tf.reshape(flow_width, [3, 3, 1, 1])
        flow_width_filter = tf.tile(flow_width_filter, [1, 1, 2, 1])
        flow_height = tf.constant([[0, 0, 0], [0, 1, 0], [0, -1, 0]], tf.float32)
        flow_height_filter = tf.reshape(flow_height, [3, 3, 1, 1])
        flow_height_filter = tf.tile(flow_height_filter, [1, 1, 2, 1])
        deltaWeights["flow_width_filter"] = flow_width_filter
        deltaWeights["flow_height_filter"] = flow_height_filter

        needImageGradients = False
        deltaWeights["needImageGradients"] = needImageGradients
        if needImageGradients:
            # Calculating image derivatives
            sobel_x = tf.constant([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], tf.float32)
            sobel_x_filter = tf.reshape(sobel_x, [3, 3, 1, 1])
            sobel_y_filter = tf.transpose(sobel_x_filter, [1, 0, 2, 3])
            deltaWeights["sobel_x_filter"] = sobel_x_filter
            deltaWeights["sobel_y_filter"] = sobel_y_filter

        # Expanding part
        pr5 = slim.conv2d(pool5, 2, [3, 3], activation_fn=None, scope='pr5')
        h5 = pr5.get_shape()[1].value
        w5 = pr5.get_shape()[2].value
        pr5_input = tf.image.resize_bilinear(inputs_norm, [h5, w5])
        pr5_output = tf.image.resize_bilinear(outputs_norm, [h5, w5])
        flow_scale_5 = 0.625    # (*20/32)
        loss5, _ = loss_interp(pr5, pr5_input, pr5_output, epsilon, alpha_c, alpha_s, lambda_smooth, flow_scale_5, deltaWeights)
        upconv4 = slim.conv2d_transpose(pool5, 256, [2*scale, 2*scale], stride=scale, scope='upconv4')
        pr5to4 = slim.conv2d_transpose(pr5, 2, [2*scale, 2*scale], stride=scale, activation_fn=None, scope='up_pr5to4')
        concat4 = tf.concat(3, [pool4, upconv4, pr5to4])

        pr4 = slim.conv2d(concat4, 2, [3, 3], activation_fn=None, scope='pr4')
        h4 = pr4.get_shape()[1].value
        w4 = pr4.get_shape()[2].value
        pr4_input = tf.image.resize_bilinear(inputs_norm, [h4, w4])
        pr4_output = tf.image.resize_bilinear(outputs_norm, [h4, w4])
        flow_scale_4 = 1.25    # (*20/16)
        loss4, _ = loss_interp(pr4, pr4_input, pr4_output, epsilon, alpha_c, alpha_s, lambda_smooth, flow_scale_4, deltaWeights)
        upconv3 = slim.conv2d_transpose(concat4, 128, [2*scale, 2*scale], stride=scale, scope='upconv3')
        pr4to3 = slim.conv2d_transpose(pr4, 2, [2*scale, 2*scale], stride=scale, activation_fn=None, scope='up_pr4to3')
        concat3 = tf.concat(3, [pool3, upconv3, pr4to3])

        pr3 = slim.conv2d(concat3, 2, [3, 3], activation_fn=None, scope='pr3')
        h3 = pr3.get_shape()[1].value
        w3 = pr3.get_shape()[2].value
        pr3_input = tf.image.resize_bilinear(inputs_norm, [h3, w3])
        pr3_output = tf.image.resize_bilinear(outputs_norm, [h3, w3])
        flow_scale_3 = 2.5    # (*20/8)
        loss3, _ = loss_interp(pr3, pr3_input, pr3_output, epsilon, alpha_c, alpha_s, lambda_smooth, flow_scale_3, deltaWeights)
        upconv2 = slim.conv2d_transpose(concat3, 64, [2*scale, 2*scale], stride=scale, scope='upconv2')
        pr3to2 = slim.conv2d_transpose(pr3, 2, [2*scale, 2*scale], stride=scale, activation_fn=None, scope='up_pr3to2')
        concat2 = tf.concat(3, [pool2, upconv2, pr3to2])

        pr2 = slim.conv2d(concat2, 2, [3, 3], activation_fn=None, scope='pr2')
        h2 = pr2.get_shape()[1].value
        w2 = pr2.get_shape()[2].value
        pr2_input = tf.image.resize_bilinear(inputs_norm, [h2, w2])
        pr2_output = tf.image.resize_bilinear(outputs_norm, [h2, w2])
        flow_scale_2 = 5.0    # (*20/4)
        loss2, _ = loss_interp(pr2, pr2_input, pr2_output, epsilon, alpha_c, alpha_s, lambda_smooth, flow_scale_2, deltaWeights)
        upconv1 = slim.conv2d_transpose(concat2, 32, [2*scale, 2*scale], stride=scale, scope='upconv1')
        pr2to1 = slim.conv2d_transpose(pr2, 2, [2*scale, 2*scale], stride=scale, activation_fn=None, scope='up_pr2to1')
        concat1 = tf.concat(3, [pool1, upconv1, pr2to1])

        pr1 = slim.conv2d(concat1, 2, [3, 3], activation_fn=None, scope='pr1')
        h1 = pr1.get_shape()[1].value
        w1 = pr1.get_shape()[2].value
        pr1_input = tf.image.resize_bilinear(inputs_norm, [h1, w1])
        pr1_output = tf.image.resize_bilinear(outputs_norm, [h1, w1])
        flow_scale_1 = 10.0    # (*20/2) 
        loss1, prev1 = loss_interp(pr1, pr1_input, pr1_output, epsilon, alpha_c, alpha_s, lambda_smooth, flow_scale_1, deltaWeights)
        
        # Adding intermediate losses
        all_loss = loss_weight[0]*loss1["total"] + loss_weight[1]*loss2["total"] + loss_weight[2]*loss3["total"] + \
                    loss_weight[3]*loss4["total"] + loss_weight[4]*loss5["total"] 
        slim.losses.add_loss(all_loss)

        losses = [loss1, loss2, loss3, loss4, loss5]
        flows_all = [pr1*flow_scale_1, pr2*flow_scale_2, pr3*flow_scale_3, pr4*flow_scale_4, pr5*flow_scale_5]
        
        return losses, flows_all, prev1


def loss_interp(flows, inputs, outputs, epsilon, alpha_c, alpha_s, lambda_smooth, flow_scale, deltaWeights):

    shape = inputs.get_shape()
    shape = [int(dim) for dim in shape]
    num_batch = shape[0]
    height = shape[1]
    width = shape[2]
    channels = shape[3]
    flow_channels = channels/3*2

    needMask = True
    needImageGradients = deltaWeights["needImageGradients"]
    # Create border mask for image
    border_ratio = 0.1
    shortestDim = height
    borderWidth = int(np.ceil(shortestDim * border_ratio))
    smallerMask = tf.ones([height-2*borderWidth, width-2*borderWidth])
    borderMask = tf.pad(smallerMask, [[borderWidth,borderWidth], [borderWidth,borderWidth]], "CONSTANT")
    borderMask = tf.tile(tf.expand_dims(borderMask, 0), [num_batch, 1, 1])
    borderMaskImg = tf.tile(tf.expand_dims(borderMask, 3), [1, 1, 1, channels])
    borderMaskFlow = tf.tile(tf.expand_dims(borderMask, 3), [1, 1, 1, flow_channels])

    # Create smoothness border mask for optical flow
    smallerSmoothMaskx = tf.ones([height-1, width])
    smallerSmoothMasky = tf.ones([height, width-1])
    smoothnessMaskx = tf.pad(smallerSmoothMaskx, [[0,1], [0,0]], "CONSTANT")    # vertical
    smoothnessMasky = tf.pad(smallerSmoothMasky, [[0,0], [0,1]], "CONSTANT")    # horizontal
    smoothnessMask = tf.pack([smoothnessMasky, smoothnessMaskx], axis=2)
    smoothnessMask = tf.tile(tf.expand_dims(smoothnessMask, 0), [num_batch, 1, 1, 1])

    inputs_flat = tf.reshape(inputs, [num_batch, -1, channels])
    outputs_flat = tf.reshape(outputs, [num_batch, -1, channels])
    borderMask_flat = tf.reshape(borderMaskImg, [num_batch, -1, channels])

    scaled_flows = tf.mul(flows, flow_scale)
    flows_flat = tf.reshape(scaled_flows, [num_batch, -1, flow_channels])
    floor_flows = tf.to_int32(tf.floor(flows_flat))
    weights_flows = flows_flat - tf.floor(flows_flat)

    # Construct the grids
    pos_x = tf.range(height)
    pos_x = tf.tile(tf.expand_dims(pos_x, 1), [1, width])
    pos_x = tf.reshape(pos_x, [-1])
    pos_y = tf.range(width)
    pos_y = tf.tile(tf.expand_dims(pos_y, 0), [height, 1])
    pos_y = tf.reshape(pos_y, [-1])
    zero = tf.zeros([], dtype='int32')

    # Warp two images based on optical flow
    batch = []
    for b in range(num_batch):
        channel = []
        x = floor_flows[b, :, 0]    # U, horizontal displacement
        y = floor_flows[b, :, 1]    # V, vertical displacement
        xw = weights_flows[b, :, 0]
        yw = weights_flows[b, :, 1]

        for c in range(channels):

            x0 = pos_y + x
            x1 = x0 + 1
            y0 = pos_x + y
            y1 = y0 + 1

            x0 = tf.clip_by_value(x0, zero, width-1)
            x1 = tf.clip_by_value(x1, zero, width-1)
            y0 = tf.clip_by_value(y0, zero, height-1)
            y1 = tf.clip_by_value(y1, zero, height-1)

            idx_a = y0 * width + x0
            idx_b = y1 * width + x0
            idx_c = y0 * width + x1
            idx_d = y1 * width + x1

            Ia = tf.gather(outputs_flat[b, :, c], idx_a)
            Ib = tf.gather(outputs_flat[b, :, c], idx_b)
            Ic = tf.gather(outputs_flat[b, :, c], idx_c)
            Id = tf.gather(outputs_flat[b, :, c], idx_d)

            wa = (1-xw) * (1-yw)
            wb = (1-xw) * yw
            wc = xw * (1-yw)
            wd = xw * yw

            img = tf.mul(Ia, wa) + tf.mul(Ib, wb) + tf.mul(Ic, wc) + tf.mul(Id, wd)
            channel.append(img)
        batch.append(tf.pack(channel, axis=1))
    reconstructs = tf.pack(batch)
    
    # result = []
    # Calculating image gradients
    if needImageGradients:
        rgb_images_list = []
        for b_idx in xrange(num_batch):
            image_idx = inputs[b_idx,:,:,:]
            max_value = tf.reduce_max(image_idx)
            min_value = tf.reduce_min(image_idx)
            intensity_range = max_value - min_value
            image_idx = tf.truediv(tf.scalar_mul(255.0, tf.sub(image_idx, min_value)), intensity_range)
            image_idx_clip = tf.clip_by_value(tf.to_int32(image_idx), zero, 255)
            rgb_images_list.append(image_idx_clip)

        rgb_images = tf.pack(rgb_images_list, axis=0)
        # result.append(rgb_images)
        inputs_gray = tf.to_float(tf.image.rgb_to_grayscale(rgb_images))
        # result.append(inputs_gray)
        img_gradients_horizontal = tf.nn.depthwise_conv2d(inputs_gray, deltaWeights["sobel_x_filter"], [1,1,1,1], padding="SAME")
        img_gradients_vertical = tf.nn.depthwise_conv2d(inputs_gray, deltaWeights["sobel_y_filter"], [1,1,1,1], padding="SAME")
        gradientsMag = tf.sqrt(tf.pow(img_gradients_horizontal, 2) + tf.pow(img_gradients_vertical, 2))
        # result.append(gradientsMag)
        gradients_list = []
        for b_idx in xrange(num_batch):
            grad_idx = gradientsMag[b_idx,:,:,:]
            max_value = tf.reduce_max(grad_idx)
            min_value = tf.reduce_min(grad_idx)
            intensity_range_grad = max_value - min_value
            grad_idx = tf.truediv(tf.scalar_mul(1.0, tf.sub(grad_idx, min_value)), intensity_range_grad)
            grad_idx_clip = tf.clip_by_value(grad_idx, 0.0, 1.0)
            gradients_list.append(grad_idx_clip)

        gradientsMask = tf.pack(gradients_list, axis=0)
        gradientsMask_rgb = tf.tile(gradientsMask, [1,1,1,3])
        gradientsMask_flat = tf.reshape(gradientsMask_rgb, [num_batch, -1, channels])

        gradientsMaskFlow = tf.sub(1.0, gradientsMask)
        gradientsMask_flow = tf.tile(gradientsMaskFlow, [1,1,1,2])
        # result.append(gradientsMask_rgb)

    # Recostruction loss
    diff_reconstruct = tf.scalar_mul(255.0, tf.sub(reconstructs, inputs_flat))
    eleWiseLoss = tf.pow(tf.square(diff_reconstruct) + tf.square(epsilon), alpha_c)
    Charbonnier_reconstruct = 0.0
    numValidPixels = 0.0

    if needMask:
        eleWiseLoss = tf.mul(borderMask_flat, eleWiseLoss)
        if needImageGradients:
            eleWiseLoss = tf.mul(gradientsMask_flat, eleWiseLoss)
        validPixels = tf.equal(borderMask_flat, tf.ones_like(borderMask_flat))
        numValidPixels = tf.to_float(tf.reduce_sum(tf.to_int32(validPixels)))
        Charbonnier_reconstruct = tf.reduce_sum(eleWiseLoss) / numValidPixels
    else:
        Charbonnier_reconstruct = tf.reduce_mean(eleWiseLoss)

    # Smoothness loss
    horizontal_gradients = tf.nn.depthwise_conv2d(flows, deltaWeights["flow_width_filter"], [1,1,1,1], padding="SAME") 
    vertical_gradients   = tf.nn.depthwise_conv2d(flows, deltaWeights["flow_height_filter"], [1,1,1,1], padding="SAME") 
    U_delta = tf.pack([horizontal_gradients[:,:,:,0], vertical_gradients[:,:,:,0]], axis=3)
    V_delta = tf.pack([horizontal_gradients[:,:,:,1], vertical_gradients[:,:,:,1]], axis=3)
    
    U_loss = 0.0
    V_loss = 0.0
    numValidFlows = numValidPixels/3*2
    if needMask:
        U_delta_clean = tf.mul(U_delta, smoothnessMask)
        V_delta_clean = tf.mul(V_delta, smoothnessMask)

        eleWiseULoss = tf.pow(tf.square(U_delta_clean) + tf.square(epsilon), alpha_s)
        if needImageGradients:
            eleWiseULoss = tf.mul(gradientsMask_flow, eleWiseULoss)
        eleWiseULoss = tf.mul(borderMaskFlow, eleWiseULoss)
        U_loss = tf.reduce_sum(eleWiseULoss) / numValidFlows

        eleWiseVLoss = tf.pow(tf.square(V_delta_clean) + tf.square(epsilon), alpha_s)
        if needImageGradients:
            eleWiseVLoss = tf.mul(gradientsMask_flow, eleWiseVLoss)
        eleWiseVLoss = tf.mul(borderMaskFlow, eleWiseVLoss)
        V_loss = tf.reduce_sum(eleWiseVLoss) / numValidFlows
    else:
        U_loss = tf.reduce_mean(tf.pow(tf.square(U_delta)  + tf.square(epsilon), alpha_s)) 
        V_loss = tf.reduce_mean(tf.pow(tf.square(V_delta)  + tf.square(epsilon), alpha_s))
    loss_smooth = U_loss + V_loss

    total_loss = Charbonnier_reconstruct + lambda_smooth * loss_smooth
    # Define a loss structure
    lossDict = {}
    lossDict["total"] = total_loss
    lossDict["Charbonnier_reconstruct"] = Charbonnier_reconstruct
    lossDict["U_loss"] = U_loss
    lossDict["V_loss"] = V_loss
    # lossDict["result"] = result

    return lossDict, tf.reshape(reconstructs, [num_batch, height, width, 3])