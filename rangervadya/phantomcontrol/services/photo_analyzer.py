import torch
import torchvision.transforms as transforms
from torchvision import models
from PIL import Image
import os
import urllib.request
import logging

logger = logging.getLogger(__name__)

_model = None
_labels = None

def get_model():
    global _model
    if _model is None:
        try:
            device = torch.device('cpu')
            _model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
            _model = _model.to(device)
            _model.eval()
            logger.info("Модель ResNet18 успешно загружена на CPU")
        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}", exc_info=True)
            raise
    return _model

def get_labels():
    global _labels
    if _labels is None:
        try:
            url = "https://raw.githubusercontent.com/pytorch/hub/master/imagenet_classes.txt"
            with urllib.request.urlopen(url) as f:
                _labels = [line.decode('utf-8').strip() for line in f.readlines()]
            logger.info(f"Загружено {len(_labels)} меток ImageNet")
        except Exception as e:
            logger.error(f"Ошибка загрузки меток: {e}")
            _labels = []
    return _labels

transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

TRENDING_KEYWORDS = ['sunglass', 'jacket', 'boot', 'sneaker', 'watch', 'perfume', 'backpack', 'bag', 'hat', 'scarf']
SEASONAL_KEYWORDS_WINTER = ['jacket', 'coat', 'scarf', 'glove', 'boot']
SEASONAL_KEYWORDS_SUMMER = ['sunglass', 'shorts', 't-shirt', 'sandals', 'hat']

def analyze_photo(image_path):
    # Возвращаем словарь с гарантированными ключами даже при ошибке
    default_result = {
        'category': 'неизвестно',
        'main_confidence': 0.0,
        'recommendation': 'Ошибка анализа ❌',
        'reason': 'Не удалось распознать изображение',
        'all_predictions': [],
        'is_trending': False,
        'is_seasonal': False
    }
    
    if not os.path.exists(image_path):
        logger.error(f"Файл не найден: {image_path}")
        default_result['reason'] = f"Файл не найден: {image_path}"
        return default_result
    
    try:
        logger.info(f"Начинаем анализ файла: {image_path}")
        image = Image.open(image_path).convert('RGB')
        input_tensor = transform(image).unsqueeze(0)
        model = get_model()
        device = torch.device('cpu')
        input_tensor = input_tensor.to(device)
        with torch.no_grad():
            output = model(input_tensor)
            probabilities = torch.nn.functional.softmax(output[0], dim=0)
            top_probs, top_indices = torch.topk(probabilities, 5)
        labels = get_labels()
        predictions = []
        for i in range(5):
            idx = top_indices[i].item()
            prob = top_probs[i].item()
            label = labels[idx] if labels and idx < len(labels) else f"Class {idx}"
            predictions.append((label, prob))
            logger.info(f"Prediction {i}: {label} ({prob:.2f})")
        main_label, main_prob = predictions[0]
        category = main_label.split(',')[0].strip()
        
        is_trending = any(kw in category.lower() for kw in TRENDING_KEYWORDS)
        is_seasonal = any(kw in category.lower() for kw in SEASONAL_KEYWORDS_WINTER + SEASONAL_KEYWORDS_SUMMER)
        
        # Жёсткая логика рекомендации (порог 0.85)
        if main_prob > 0.85 and is_trending:
            recommendation = "Рекомендуем закупить! 🔥"
            reason = f"Модель уверена на {main_prob*100:.1f}%, категория '{category}' в тренде."
        elif main_prob > 0.85 and is_seasonal:
            recommendation = "С осторожностью (сезонный товар). ⚠️"
            reason = f"Высокая уверенность ({main_prob*100:.1f}%), но товар сезонный. Проверьте спрос."
        elif main_prob > 0.85:
            recommendation = "С осторожностью (не в тренде). ⚠️"
            reason = f"Уверенность {main_prob*100:.1f}%, но категория '{category}' не в тренде."
        elif main_prob > 0.6:
            recommendation = "Возможно, стоит рассмотреть. 🤔"
            reason = f"Уверенность {main_prob*100:.1f}%. Категория '{category}'."
        else:
            recommendation = "Не рекомендуется. ❌"
            reason = f"Модель не уверена ({main_prob*100:.1f}%). Возможно, это {predictions[1][0]} или {predictions[2][0]}."
        
        logger.info(f"Результат: {recommendation}")
        return {
            'category': category,
            'main_confidence': main_prob,
            'recommendation': recommendation,
            'reason': reason,
            'all_predictions': predictions,
            'is_trending': is_trending,
            'is_seasonal': is_seasonal
        }
    except Exception as e:
        logger.error(f"Ошибка анализа: {e}", exc_info=True)
        default_result['reason'] = f"Ошибка: {str(e)}"
        return default_result